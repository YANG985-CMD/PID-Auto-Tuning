function report=trainSpeedLoopFinalStreams(checkpoint,dataset,outputDir,bcWeight,epochs)
% Multiseed native TD3 from audited prior + finalized live streams.
% Stationary Actor cannot copy its Kp input or infer actions from trial clock.
arguments
    checkpoint (1,1) string
    dataset (1,1) string
    outputDir (1,1) string
    bcWeight (1,1) double {mustBeNonnegative} = 2.5
    epochs (1,1) double {mustBeInteger,mustBePositive} = 10
end
assert(epochs<=30 && ~isfolder(outputDir));mkdir(outputDir);
loaded=load(checkpoint,'contract','candidateReport');contract=loaded.contract;
assert(loaded.candidateReport.session_validation_passed && ~loaded.candidateReport.session_shutdown_pending);
assert(~loaded.candidateReport.deployment_allowed && ~loaded.candidateReport.performance_claim_allowed);
physical=validateSpeedLoopResponseReplay(dataset,[1;0]);
[replay,c]=prepareMotorCausalReplay(physical,"absolute-target",contract.state_standardized, ...
    ObservationProfile="history20-40",LearningTask="continuing");
assert(isequal(c.state_center,contract.state_center) && isequal(c.state_scale,contract.state_scale));
keys=strings(0,1);boots=strings(0,1);
for r=loaded.candidateReport.consumed_windows(:)'
    assert(motorFileSHA256(r.file)==string(r.sha256));w=jsondecode(fileread(r.file));
    assert(~any(string(w.boot_id)==string(physical.summary.all_boot_ids)));
    [e,key]=motorLiveWindowExperience(w,contract);assert(key==string(r.physical_key) && ~any(keys==key));
    keys(end+1)=key;boots(end+1)=string(w.boot_id); %#ok<AGROW>
    row=struct(observation=double(e.Observation{1}),next_observation=double(e.NextObservation{1}), ...
        action_normalized=double(e.Action{1}),reward=e.Reward,learning_is_done=false, ...
        state=engineering(w.state),next_state=engineering(w.response(end)), ...
        boot_id=string(w.boot_id),telemetry_seq_start=w.state.seq,physical_delta_action=w.physical_delta_action);
    replay.train{end+1}=row;
end
assert(numel(replay.train)==loaded.candidateReport.replay_count);
mask=ones(10,1);mask([8 10])=0;
contract.actor_input_mask=mask';contract.action_mask=[1 0];
contract.actor_elapsed_time_masked=true;contract.actor_actual_kp_input_masked=true;
contract.online_learning=false;contract.runtime_compatible=false;
lower=0;
if isfield(contract,'stream_gain_profile')
    spec=motorStreamGainSpec(string(contract.stream_gain_profile));lower=spec.action_lower_limit(1);
end
contract.action_lower_limit=[lower -1];contract.action_upper_limit=[.5 1];
contract.actor_output_affine_scale=[(.5-lower)/2 1];
contract.actor_output_affine_bias=[(.5+lower)/2 0];
prior=mean(cellfun(@(r)r.reward,replay.train))/(1-.99);
report=struct(source="finalized-real-stream-multiseed-td3",learning_contract=contract, ...
    parent_checkpoint_sha256=motorFileSHA256(checkpoint),prior_dataset_sha256=string(physical.summary.dataset_sha256), ...
    finalized_stream_manifest=loaded.candidateReport.consumed_windows,stream_boots=unique(boots), ...
    training_experiences=numel(replay.train),validation_experiences=numel(replay.validation), ...
    action_mask=[1 0],fixed_ki=.00144,seeds=[7 17 27],behavior_cloning_weight=bcWeight, ...
    critic_initial_value=prior,critic_l2_regularization_factor=0,steps_per_seed=epochs*40, ...
    seed_reports=[],td3_training_performed=false,hardware_accessed=false, ...
    ordinary_live_admission=false,deployment_allowed=false,performance_claim_allowed=false, ...
    temperature_gate_modified=false,independent_physical_actor_validation_performed=false);
write(fullfile(outputDir,'study-contract.json'),report);
results=cell(3,1);
for index=1:3
    seed=report.seeds(index);
    experimentalAgent=createMotorTD3(seed,[1;0],bcWeight,ActorInputMask=mask, ...
        CriticInitialValue=prior,CriticL2RegularizationFactor=0,TargetNoiseStandardDeviation=[.05;.05], ...
        TargetNoiseClip=.1,ActionLowerLimit=[lower;-1],ActionUpperLimit=[.5;1]);
    before=getModel(getActor(experimentalAgent));
    opts=experimentalAgent.AgentOptions;
    opts.InfoToSave=struct(ExperienceBuffer=true,Optimizer=true,PolicyState=true,Target=true);
    experimentalAgent.AgentOptions=opts;
    for k=1:numel(replay.train)
        r=replay.train{k};e=struct('Observation',{{single(r.observation(:))}},'Action',{{single(r.action_normalized(:))}}, ...
            'Reward',r.reward,'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
        validateExperience(experimentalAgent.ExperienceBuffer,e);append(experimentalAgent.ExperienceBuffer,e);
    end
    stats=trainFromData(experimentalAgent,rlTrainingFromDataOptions('MaxEpochs',epochs,'NumStepsPerEpoch',40, ...
        'Plots','none','Verbose',false,'SaveAgentCriteria','none'));
    diagnostics=diagnoseMotorTD3Policy(experimentalAgent,replay.validation);
    a=diagnostics.predictions{:,{'actor_kp_action','actor_ki_action'}};
    gains=a.*contract.gain_step_scale+contract.encoded_baseline_gains;
    assert(all(a(:,1)>=lower-1e-6 & a(:,1)<=.5+1e-6) && all(a(:,2)==0));
    assert(all(gains(:,2)==double(single(.00144))));
    row=struct(seed=seed,learning_contract=contract,training_steps=double(stats.TotalSteps(end)), ...
        actor_weight_change_l2=distance(before,getModel(getActor(experimentalAgent))), ...
        validation=diagnostics.metrics,critic_numerical_screen=screenMotorCriticDiagnostics(diagnostics.metrics), ...
        candidate_kp_range=[min(gains(:,1)) max(gains(:,1))],action_bounds_passed=true,gain_bounds_passed=true, ...
        deployment_allowed=false,performance_claim_allowed=false,runtime_compatible=false);
    candidateReport=row;save(fullfile(outputDir,"candidate-seed-"+seed+".mat"),'experimentalAgent','contract','candidateReport');
    row.checkpoint_sha256=motorFileSHA256(fullfile(outputDir,"candidate-seed-"+seed+".mat"));
    diagnostics.predictions.candidate_kp=gains(:,1);diagnostics.predictions.candidate_ki=gains(:,2);
    writetable(diagnostics.predictions,fullfile(outputDir,"holdout-seed-"+seed+".csv"));
    results{index}=row;write(fullfile(outputDir,"seed-"+seed+"-summary.json"),row);
    fprintf('Finished fixed-mask real-stream TD3 seed %d, %d native steps\n',seed,row.training_steps);
end
report.seed_reports=[results{:}];report.td3_training_performed=true;
report.total_gradient_steps=sum([report.seed_reports.training_steps]);
report.candidate_admission=false;report.reason="Only frozen-state diagnostics; independent physical Actor comparison remains absent";
write(fullfile(outputDir,'training-summary.json'),report);
end

function x=engineering(t)
x=[t.speed_ref t.speed t.speed_ref-t.speed t.error_history t.integral_output t.current t.vbus t.kp t.ki t.elapsed_ms];
end
function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
function d=distance(a,b)
d=0;for k=1:height(a.Learnables),d=d+sum(double(extractdata(b.Learnables.Value{k}-a.Learnables.Value{k})).^2,'all');end;d=sqrt(d);
end
