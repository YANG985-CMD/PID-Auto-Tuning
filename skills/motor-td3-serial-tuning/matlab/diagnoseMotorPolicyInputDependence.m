function report=diagnoseMotorPolicyInputDependence(checkpoint,dataset,output)
% Input ablations diagnose shortcuts; they are not physical counterfactuals.
arguments
    checkpoint (1,1) string
    dataset (1,1) string
    output (1,1) string
end
loaded=load(checkpoint,'experimentalAgent','reportSeed');
contract=loaded.reportSeed.learning_contract;
assert(contract.action_coordinates=="absolute-target" && loaded.reportSeed.ki_masked);
physical=validateSpeedLoopResponseReplay(dataset,[1;0]);
rows=physical.validation;
profile="physical";task="continuing";
if isfield(contract,'observation_profile'),profile=string(contract.observation_profile);end
if isfield(contract,'learning_task'),task=string(contract.learning_task);end
[learning,prepared]=prepareMotorCausalReplay(physical, ...
    string(contract.action_coordinates),contract.state_standardized, ...
    ObservationProfile=profile,LearningTask=task);
assert(all(abs(prepared.state_center(:)-contract.state_center(:))<1e-8) && ...
    all(abs(prepared.state_scale(:)-contract.state_scale(:))<1e-8));
obs=cell2mat(cellfun(@(r)r.observation(:),learning.validation,UniformOutput=false)');
fixed=obs;
fixed(8,:)=(contract.encoded_baseline_gains(1)/contract.engineering_state_scale(8)- ...
    contract.state_center(8))/contract.state_scale(8);
actor=getActor(loaded.experimentalAgent);
normal=getAction(actor,{single(obs)});normal=double(normal{1}(1,:));
fixedAction=getAction(actor,{single(fixed)});fixedAction=double(fixedAction{1}(1,:));
actual=cellfun(@(r)(r.action_applied(1)-contract.encoded_baseline_gains(1))/contract.gain_step_scale(1),rows)';
baseline=actual<1e-6;probe=actual>.49;
assert(any(baseline) && any(probe));
report=struct(schema_version=1,seed=loaded.reportSeed.seed,checkpoint_sha256=motorFileSHA256(checkpoint), ...
    dataset_sha256=physical.summary.dataset_sha256,validation_only=true, ...
    actor_action_std=std(normal),fixed_current_kp_action_std=std(fixedAction), ...
    actual_current_gain_group_actor_means=[mean(normal(baseline)),mean(normal(probe))], ...
    fixed_kp_group_actor_means=[mean(fixedAction(baseline)),mean(fixedAction(probe))], ...
    mean_abs_effect_of_current_kp_input=mean(abs(normal-fixedAction)), ...
    variance_remaining_fraction=var(fixedAction)/max(var(normal),eps), ...
    not_physical_counterfactual=true,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);
closer=onCleanup(@()fclose(f));
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'),'uint8');
end
