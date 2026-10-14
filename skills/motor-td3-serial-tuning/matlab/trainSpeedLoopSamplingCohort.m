function report=trainSpeedLoopSamplingCohort(checkpoint,folders,batchContract,output,epochs,bcWeight,options)
% Fresh native TD3 from post-fix physical data; whole third boot is held out.
arguments
    checkpoint (1,1) string
    folders (:,1) string
    batchContract (1,1) string
    output (1,1) string
    epochs (1,1) double {mustBeInteger,mustBePositive}=10
    bcWeight (1,1) double {mustBeNonnegative}=2.5
    options.CriticInputMask (10,1) double=ones(10,1)
    options.PrioritizedReplay (1,1) logical=false
    options.Profiles (1,:) string {mustBeMember(options.Profiles,["legacy","constrained"])}=["legacy","constrained"]
    options.ActorInputMask (10,1) double=[ones(7,1);0;1;0]
    options.FixedReferenceCohort (1,1) logical=false
end
assert(epochs<=20 && ~isfolder(output));mkdir(output);
batch=jsondecode(fileread(batchContract));
if options.FixedReferenceCohort
    assert(numel(folders)==2 && batch.split_predeclared_before_capture && batch.maximum_batch_motion_seconds==48);
    assert(isequal(string(batch.split(:)),["train";"validation"]));trainCount=1;
    expectedFirmware="g431-speedloop-pi-fixedref-24s-v20";
else
    assert(numel(folders)==3);
    assert(isequal(batch.training_boot_indices,[0;1]) || isequal(batch.training_boot_indices,[0 1]));
    assert(isequal(batch.validation_boot_indices,2) && batch.split_predeclared_before_holdout_capture);
    trainCount=2;expectedFirmware="g431-speedloop-pi-lower8-24s-v19";
end
s=load(checkpoint,'contract');contract=s.contract;
contract.stream_gain_profile="lower8-sampling";spec=motorStreamGainSpec(contract.stream_gain_profile);
contract.action_lower_limit=spec.action_lower_limit;contract.action_upper_limit=spec.action_upper_limit;
contract.actor_output_affine_scale=spec.output_scale;contract.actor_output_affine_bias=spec.output_bias;
mask=options.ActorInputMask;contract.actor_input_mask=mask';contract.action_mask=[1 0];
contract.actor_elapsed_time_masked=mask(10)==0;contract.actor_actual_kp_input_masked=mask(8)==0;
contract.online_learning=false;contract.runtime_compatible=false;
contract.older_fixed_cadence_replay_excluded=true;
contract.critic_input_mask=options.CriticInputMask';
train={};validation={};manifest=struct([]);boots=strings(numel(folders),1);seen=strings(0,1);
for index=1:numel(folders)
    folder=folders(index);trial=jsondecode(fileread(fullfile(folder,'trial','summary.json')));
    ending=jsondecode(fileread(fullfile(folder,'stream','session-ended.json')));
    assert(trial.passed && ~trial.actor_applied && trial.final_irq_fault==0 && trial.final_tx_fault==0);
    assert(string(trial.firmware_id)==expectedFirmware);
    assert(ending.physical_trial_passed && ending.stop_acknowledged && ending.core_halted && ending.can_released);
    if index>trainCount,assert(string(trial.predeclared_split)=="validation" && trial.capture_only);end
    raw=cellfun(@jsondecode,cellstr(splitlines(strtrim(fileread(fullfile(folder,'trial','telemetry.jsonl'))))),UniformOutput=false);
    packets=[raw{:}];boots(index)=string(packets(1).boot_id);
    assert(all(string({packets.boot_id})==boots(index)) && all([packets.fault]==0));
    if options.FixedReferenceCohort,assert(all([packets.speed_ref]==1000));end
    files=dir(fullfile(folder,'stream','window-*.json'));assert(numel(files)>100);
    for f=files'
        file=string(fullfile(f.folder,f.name));w=jsondecode(fileread(file));
        assert(string(w.boot_id)==boots(index));[e,key]=motorLiveWindowExperience(w,contract);
        assert(~any(seen==key));seen(end+1)=key; %#ok<AGROW>
        for t=[w.state_history(:);w.response(:)]'
            actual=packets([packets.seq]==t.seq);assert(isscalar(actual) && isequal(actual,t));
        end
        z=w.response;delta=w.physical_delta_action(1);
        dt=diff([z.t_us]);error=[z.speed_ref]-[z.speed];
        mse=sum(.5*(error(1:end-1).^2+error(2:end).^2).*dt)/sum(dt);
        current=max([z.current]);speed=max(abs([z.speed]));sat=double([z.current]>=1.98);
        sat=sum(.5*(sat(1:end-1)+sat(2:end)).*dt)/sum(dt);
        constrained=-mse/1e6-.3*(current/2)^2-.25*max(0,(speed-1500)/300)^2-.25*sat-.0005*delta^2;
        row=struct(observation=double(e.Observation{1}),next_observation=double(e.NextObservation{1}), ...
            action_normalized=double(e.Action{1}),reward=e.Reward,legacy_reward=e.Reward, ...
            constrained_reward=constrained,actual_action_changed=w.state.kp~=w.action_applied(1), ...
            learning_is_done=false,boot_id=boots(index),telemetry_seq_start=w.state.seq);
        if index<=trainCount,train{end+1}=row;else,validation{end+1}=row;end %#ok<AGROW>
        record=struct(file=file,sha256=motorFileSHA256(file),physical_key=key,boot_index=index-1, ...
            split=string(ternary(index<=trainCount,'train','validation')),legacy_reward=e.Reward,constrained_reward=constrained);
        if isempty(manifest),manifest=record;else,manifest(end+1)=record;end %#ok<AGROW>
    end
end
assert(numel(unique(boots))==numel(folders) && numel(train)>=128 && numel(validation)>100);
train=train(:);validation=validation(:);
report=struct(source="fresh-post-sampling-fix-real-motor-TD3",learning_contract=contract, ...
    normalization_source_checkpoint_sha256=motorFileSHA256(checkpoint),older_replay_used_for_training=false, ...
    batch_contract_sha256=motorFileSHA256(batchContract),train_boots=boots(1:trainCount),validation_boots=boots(trainCount+1:end), ...
    train_windows=numel(train),validation_windows=numel(validation),input_manifest=manifest, ...
    profiles=options.Profiles,seeds=[7 17 27],steps_per_candidate=epochs*40, ...
    behavior_cloning_regularizer_weight=bcWeight, ...
    prioritized_replay=options.PrioritizedReplay,critic_input_mask=options.CriticInputMask', ...
    unique_training_experiences_counted_once=true,training_action_change_windows=sum(cellfun(@(r)r.actual_action_changed,train)), ...
    fixed_reference_cohort=options.FixedReferenceCohort,actor_input_mask=mask', ...
    reward_coefficients=struct(legacy=[.12 .08 .1 .005],constrained=[.3 .25 .25 .0005]), ...
    reward_order="current,near-speed,saturation,action-change",old_rewards_retained=true, ...
    weight_choice_fitted_to_holdout=false,actor_applied=false,physical_actor_test_performed=false, ...
    deployment_allowed=false,performance_claim_allowed=false,candidates=struct([]));
write(fullfile(output,'study-contract.json'),report);
for profile=report.profiles
    selected=train;heldout=validation;
    for k=1:numel(selected),selected{k}.reward=selected{k}.(profile+"_reward");end
    for k=1:numel(heldout),heldout{k}.reward=heldout{k}.(profile+"_reward");end
    prior=mean(cellfun(@(r)r.reward,selected))/(1-.99);
    for seed=report.seeds
        agent=createMotorTD3(seed,[1;0],bcWeight,ActorInputMask=mask,CriticInitialValue=prior, ...
            CriticInputMask=options.CriticInputMask, ...
            CriticL2RegularizationFactor=0,ActionLowerLimit=spec.action_lower_limit(:), ...
            ActionUpperLimit=spec.action_upper_limit(:),TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1);
        saveOptions=agent.AgentOptions;saveOptions.InfoToSave=struct(ExperienceBuffer=true,Optimizer=true,PolicyState=true,Target=true);agent.AgentOptions=saveOptions;
        if options.PrioritizedReplay
            replayMemory=rlPrioritizedReplayMemory(getObservationInfo(agent),getActionInfo(agent),10000);
            replayMemory.PriorityExponent=.6;replayMemory.InitialImportanceSamplingExponent=.4;
            replayMemory.NumAnnealingSteps=epochs*40;agent.ExperienceBuffer=replayMemory;
        end
        for k=1:numel(selected)
            r=selected{k};e=struct('Observation',{{single(r.observation(:))}},'Action',{{single(r.action_normalized(:))}}, ...
                'Reward',r.reward,'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
            validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);
        end
        stats=trainFromData(agent,rlTrainingFromDataOptions('MaxEpochs',epochs,'NumStepsPerEpoch',40, ...
            'Plots','none','Verbose',false,'SaveAgentCriteria','none'));
        assert(agent.ExperienceBuffer.Length==numel(train));
        d=diagnoseMotorTD3Policy(agent,heldout,"continuing",[-.9875 0]);
        rng(991+seed);obs=single(rand(10,128)*10-5);other=obs;other(mask==0,:)=-other(mask==0,:);
        actor=getActor(agent);a=getAction(actor,{obs});b=getAction(actor,{other});
        assert(isequal(a{1},b{1}) && all(a{1}(2,:)==0) && all(a{1}(1,:)>=-1 & a{1}(1,:)<=0));
        candidateReport=struct(seed=seed,reward_profile=profile,learning_contract=contract, ...
            train_windows=numel(train),validation_windows=numel(validation),training_steps=double(stats.TotalSteps(end)), ...
            validation=d.metrics,critic_numerical_screen=screenMotorCriticDiagnostics(d.metrics), ...
            mask_invariance_passed=true,action_bounds_passed=true,ki_mask_passed=true, ...
            replay_count_after_training=agent.ExperienceBuffer.Length,replay_class=string(class(agent.ExperienceBuffer)), ...
            hardware_accessed=false,deployment_allowed=false,performance_claim_allowed=false);
        name="candidate-"+profile+"-seed-"+seed;experimentalAgent=agent; %#ok<NASGU>
        save(fullfile(output,name+".mat"),'experimentalAgent','contract','candidateReport');
        candidateReport.checkpoint_sha256=motorFileSHA256(fullfile(output,name+".mat"));
        if isempty(report.candidates),report.candidates=candidateReport;
        else,report.candidates(end+1)=candidateReport;end
        d.predictions.legacy_reward=cellfun(@(r)r.legacy_reward,heldout(:));
        d.predictions.constrained_reward=cellfun(@(r)r.constrained_reward,heldout(:));
        writetable(d.predictions,fullfile(output,name+"-holdout.csv"));
        exportMotorTD3DiagnosticJSON(fullfile(output,name+".mat"),fullfile(output,name+"-networks.json"));
        write(fullfile(output,'progress.json'),struct(finished_candidates=numel(report.candidates),candidate=name));
        fprintf('Completed fresh real-motor %s seed %d (%d native TD3 steps)\n',profile,seed,candidateReport.training_steps);
    end
end
report.td3_training_performed=true;report.total_native_steps=sum([report.candidates.training_steps]);
report.candidate_admission=false;report.reason="Held-out recorded states support diagnostics only; no frozen Actor physical comparison";
write(fullfile(output,'training-summary.json'),report);
end

function value=ternary(test,a,b)
if test,value=a;else,value=b;end
end
function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
