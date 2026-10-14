function report=runSpeedLoopAsyncTraining(checkpoint,priorDataset,streamDir,outputDir,maximumSeconds,gainProfile)
% Dedicated MATLAB process: consumes real ACK windows while CAN runs elsewhere.
% Immutable candidate versions; no device access and no automatic activation.
arguments
    checkpoint (1,1) string
    priorDataset (1,1) string
    streamDir (1,1) string
    outputDir (1,1) string
    maximumSeconds (1,1) double {mustBePositive} = 120
    gainProfile (1,1) string {mustBeMember(gainProfile,["two","interior3","lower4","lower8"])} = "two"
end
assert(maximumSeconds<=180 && startsWith(lower(outputDir),"e:\simulink\_codex_tmp\"));
assert(~isfolder(outputDir));mkdir(outputDir);
loaded=load(checkpoint);agent=loaded.experimentalAgent;previousLive=[];
if isfield(loaded,'reportSeed')
    contract=loaded.reportSeed.learning_contract;
    assert(~loaded.reportSeed.deployment_allowed && ~loaded.reportSeed.runtime_compatible);
else
    contract=loaded.contract;
    assert(~loaded.candidateReport.deployment_allowed && ~loaded.candidateReport.session_shutdown_pending);
    assert(loaded.candidateReport.session_validation_passed);
    previousLive=loaded.candidateReport.consumed_windows;
end
assert(isequal(contract.action_mask,[1 0]) && string(contract.learning_task)=="continuing");
assert(string(contract.observation_profile)=="history20-40" && string(contract.action_coordinates)=="absolute-target");
contract.stream_gain_profile=gainProfile;
learnerReset=false;
if gainProfile=="lower4" && ~isfield(contract,'lower_commission_learning_initialized')
    % Old positive-only ActionInfo cannot accept real negative experience.
    % Fresh provisional learner; retain every audited old experience below.
    agent=createMotorTD3(7,[1;0],2.5,ActionLowerLimit=[-.5;-1],ActionUpperLimit=[.5;1], ...
        CriticL2RegularizationFactor=0,TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1);
    contract.action_lower_limit=[-.5 -1];contract.action_upper_limit=[.5 1];
    contract.actor_output_affine_scale=[.5 1];contract.actor_output_affine_bias=[0 0];
    contract.actor_input_mask=ones(1,10);contract.lower_commission_learning_initialized=true;
    learnerReset=true;
end
prior=validateSpeedLoopResponseReplay(priorDataset,[1;0]);assert(prior.training_ready);
[learning,priorContract]=prepareMotorCausalReplay(prior,"absolute-target",contract.state_standardized, ...
    ObservationProfile="history20-40",LearningTask="continuing");
assert(isequal(priorContract.state_center,contract.state_center) && isequal(priorContract.state_scale,contract.state_scale));
if gainProfile=="lower8" && ~isfield(contract,'lower8_learning_initialized')
    % New negative support needs matching replay bounds. Old checkpoints remain
    % unchanged; carry over audited real experiences, explicitly reset learner.
    spec=motorStreamGainSpec(gainProfile);mask=ones(10,1);mask([8 10])=0;
    rewards=cellfun(@(r)r.reward,learning.train);
    for row=previousLive(:)'
        assert(motorFileSHA256(row.file)==string(row.sha256));
        w=jsondecode(fileread(row.file));rewards(end+1)=w.reward; %#ok<AGROW>
    end
    qPrior=mean(rewards)/(1-.99);
    agent=createMotorTD3(7,[1;0],2.5,ActionLowerLimit=spec.action_lower_limit(:), ...
        ActionUpperLimit=spec.action_upper_limit(:),ActorInputMask=mask, ...
        CriticInitialValue=qPrior,CriticL2RegularizationFactor=0, ...
        TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1);
    contract.action_lower_limit=spec.action_lower_limit;contract.action_upper_limit=spec.action_upper_limit;
    contract.actor_output_affine_scale=spec.output_scale;contract.actor_output_affine_bias=spec.output_bias;
    contract.actor_input_mask=mask';contract.actor_elapsed_time_masked=true;
    contract.actor_actual_kp_input_masked=true;contract.lower8_learning_initialized=true;
    contract.critic_initial_value=qPrior;contract.legacy_replay_capture_time_audit_required=true;
    learnerReset=true;
end
expected=numel(learning.train)+numel(previousLive);
assert(agent.ExperienceBuffer.Length==0 || agent.ExperienceBuffer.Length==expected);
restoreReplay=agent.ExperienceBuffer.Length==0;
if restoreReplay
    for k=1:numel(learning.train)
        r=learning.train{k};e=struct('Observation',{{single(r.observation(:))}}, ...
            'Action',{{single(r.action_normalized(:))}},'Reward',r.reward, ...
            'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
        validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);
    end
end
previousKeys=strings(0,1);
for row=previousLive(:)'
    assert(motorFileSHA256(row.file)==string(row.sha256));
    [e,key]=motorLiveWindowExperience(jsondecode(fileread(row.file)),contract);
    assert(key==string(row.physical_key) && ~any(previousKeys==key));
    previousKeys(end+1)=key; %#ok<AGROW>
    if restoreReplay,validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);end
end
% R2024b defaults omit replay, optimizer and target networks when saving.
% Keep them explicitly so a future process can actually continue this learner.
savedInfo=agent.AgentOptions.InfoToSave;
agentOptions=agent.AgentOptions;
agentOptions.InfoToSave=struct(ExperienceBuffer=true,Optimizer=true,PolicyState=true,Target=true);
agent.AgentOptions=agentOptions;
initialLength=agent.ExperienceBuffer.Length;actorBefore=getModel(getActor(agent));
report=struct(schema_version=1,source="MATLAB-real-time-actual-ack-TD3", ...
    initial_checkpoint_sha256=motorFileSHA256(checkpoint),initial_replay_count=initialLength, ...
    prior_dataset_sha256=string(prior.summary.dataset_sha256), ...
    initial_stream_experiences=numel(previousLive),optimizer_restored_from_checkpoint=logical(savedInfo.Optimizer), ...
    stream_gain_profile=gainProfile, ...
    learner_reset_for_new_negative_action_support=learnerReset, ...
    learner_reset_for_extended_negative_action_support=learnerReset && gainProfile=="lower8", ...
    replay_optimizer_and_targets_saved=true, ...
    live_experiences=0,gradient_steps=0,training_performed=false,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false,actor_auto_activated=false, ...
    training_process_separate_from_CAN=true,action_mask=[1 0],fixed_ki=.00144, ...
    session_shutdown_pending=true,consumed_windows=previousLive,candidate_files=strings(0,1));
writeReport(fullfile(outputDir,'ready.json'),report);
began=tic;seen=strings(0,1);keys=previousKeys;lastNext=containers.Map('KeyType','char','ValueType','double');
pending=0;candidate=0;
try
    while toc(began)<maximumSeconds
        writeReport(fullfile(outputDir,'progress.json'),struct(utc=string(datetime('now','TimeZone','UTC')), ...
            elapsed_seconds=toc(began),live_experiences=report.live_experiences,gradient_steps=report.gradient_steps));
        files=dir(fullfile(streamDir,'window-*.json'));
        for f=files(:)'
            if any(seen==string(f.name)),continue;end
            file=fullfile(f.folder,f.name);r=jsondecode(fileread(file));
            assert(~any(string(r.boot_id)==string(prior.summary.all_boot_ids)),'MotorTD3:OldBoot','Do not re-count old physical boot');
            [e,key]=motorLiveWindowExperience(r,contract);
            assert(~any(keys==key),'MotorTD3:DuplicateWindow','Repeated physical window');
            boot=char(r.boot_id);
            if isKey(lastNext,boot),assert(r.state.t_us>=lastNext(boot),'MotorTD3:Overlap','Overlapping responses');end
            lastNext(boot)=r.response(end).t_us;
            validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);
            seen(end+1)=string(f.name);keys(end+1)=key;pending=pending+1;
            report.live_experiences=report.live_experiences+1;
            row=struct(file=string(file),sha256=motorFileSHA256(file),physical_key=key, ...
                source_t_us=r.state.t_us,next_t_us=r.response(end).t_us,boot_id=string(r.boot_id));
            if isempty(report.consumed_windows),report.consumed_windows=row;
            else,report.consumed_windows(end+1)=row;end
        end
        finished=isfile(fullfile(streamDir,'session-ended.json'));
        if agent.ExperienceBuffer.Length>=128 && (pending>=16 || (finished && pending>0))
            stats=trainFromData(agent,rlTrainingFromDataOptions('MaxEpochs',1,'NumStepsPerEpoch',20, ...
                'Plots','none','Verbose',false,'SaveAgentCriteria','none'));
            report.gradient_steps=report.gradient_steps+double(stats.TotalSteps(end));
            report.training_performed=true;candidate=candidate+1;pending=0;
            report.replay_count=agent.ExperienceBuffer.Length;
            report.session_shutdown_pending=~finished;
            candidateReport=report;experimentalAgent=agent; %#ok<NASGU>
            dest=fullfile(outputDir,"candidate-"+compose('%03d',candidate)+".mat");
            save(dest,'experimentalAgent','contract','candidateReport');
            report.candidate_files(end+1)=dest;
            writeReport(fullfile(outputDir,'training-summary.json'),report);
        end
        if finished && numel(seen)==numel(files),break;end
        pause(.025);
    end
    report.finished=exist('finished','var') && finished;
    report.session_shutdown_pending=~report.finished;
    report.session_validation_passed=false;
    if report.finished
        ending=jsondecode(fileread(fullfile(streamDir,'session-ended.json')));
        report.session_validation_passed=ending.physical_trial_passed && ending.stop_acknowledged && ...
            ending.core_halted && ending.can_released && ending.final_irq_fault==0 && ending.final_tx_fault==0;
    end
    report.provisional_training_quarantined=~report.session_validation_passed;
    report.actor_weight_change_l2=distance(actorBefore,getModel(getActor(agent)));
    report.replay_count=agent.ExperienceBuffer.Length;
    if report.session_validation_passed
        experimentalAgent=agent;candidateReport=report; %#ok<NASGU>
        save(fullfile(outputDir,'resumable-candidate.mat'),'experimentalAgent','contract','candidateReport');
    end
catch ex
    report.finished=false;report.error=string(ex.identifier)+":"+string(ex.message);
    writeReport(fullfile(outputDir,'failure.json'),report);
end
writeReport(fullfile(outputDir,'training-summary.json'),report);
end

function writeReport(path,r)
blob=unicode2native(jsonencode(r,PrettyPrint=true),'UTF-8');temp=path+".part";
f=fopen(temp,'wb');assert(f>=0);fwrite(f,blob);fclose(f);movefile(temp,path,'f');
end

function d=distance(a,b)
d=0;
for k=1:height(a.Learnables),d=d+sum(double(extractdata(b.Learnables.Value{k}-a.Learnables.Value{k})).^2,'all');end
d=sqrt(d);
end
