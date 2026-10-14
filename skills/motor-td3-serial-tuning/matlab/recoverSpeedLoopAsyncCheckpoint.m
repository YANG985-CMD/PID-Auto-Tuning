function result=recoverSpeedLoopAsyncCheckpoint(checkpoint,dataset,trainingSummary,output)
% Recover omitted replay from audited raw windows. Does not perform training.
% Legacy optimizer/target state was not saved and cannot be recovered.
arguments
    checkpoint (1,1) string
    dataset (1,1) string
    trainingSummary (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(checkpoint,'experimentalAgent','contract');
candidateReport=jsondecode(fileread(trainingSummary));contract=s.contract;
assert(candidateReport.session_validation_passed && ~candidateReport.session_shutdown_pending);
assert(~candidateReport.deployment_allowed && ~candidateReport.performance_claim_allowed);
assert(s.experimentalAgent.ExperienceBuffer.Length==0);
p=validateSpeedLoopResponseReplay(dataset,[1;0]);
[learning,c]=prepareMotorCausalReplay(p,"absolute-target",contract.state_standardized, ...
    ObservationProfile="history20-40",LearningTask="continuing");
assert(isequal(c.state_center,contract.state_center) && isequal(c.state_scale,contract.state_scale));
agent=s.experimentalAgent;keys=strings(0,1);
for k=1:numel(learning.train)
    r=learning.train{k};e=struct('Observation',{{single(r.observation(:))}},'Action',{{single(r.action_normalized(:))}}, ...
        'Reward',r.reward,'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
    validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);
end
for row=candidateReport.consumed_windows(:)'
    assert(motorFileSHA256(row.file)==string(row.sha256));
    r=jsondecode(fileread(row.file));assert(~any(string(r.boot_id)==string(p.summary.all_boot_ids)));
    [e,key]=motorLiveWindowExperience(r,contract);assert(~any(keys==key));keys(end+1)=key; %#ok<AGROW>
    validateExperience(agent.ExperienceBuffer,e);append(agent.ExperienceBuffer,e);
end
assert(agent.ExperienceBuffer.Length==candidateReport.replay_count);
options=agent.AgentOptions;options.InfoToSave=struct(ExperienceBuffer=true,Optimizer=true,PolicyState=true,Target=true);
agent.AgentOptions=options;
candidateReport.legacy_checkpoint_sha256=motorFileSHA256(checkpoint);
candidateReport.optimizer_reset_after_legacy_save=true;
candidateReport.target_networks_reset_after_legacy_save=true;
candidateReport.replay_optimizer_and_targets_saved=true;
candidateReport.recovery_gradient_steps=0;
experimentalAgent=agent;save(output,'experimentalAgent','contract','candidateReport');
check=load(output,'experimentalAgent');assert(check.experimentalAgent.ExperienceBuffer.Length==candidateReport.replay_count);
a=getModel(getActor(agent));b=getModel(getActor(check.experimentalAgent));
assert(isequal(a.Learnables,b.Learnables));
result=struct(recovered_checkpoint_sha256=motorFileSHA256(output),replay_count=candidateReport.replay_count, ...
    actor_weights_unchanged=true,recovery_gradient_steps=0,optimizer_reset=true,target_networks_reset=true,hardware_accessed=false);
disp(jsonencode(result));
end
