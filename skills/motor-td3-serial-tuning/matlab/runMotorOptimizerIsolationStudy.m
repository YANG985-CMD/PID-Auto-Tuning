function report=runMotorOptimizerIsolationStudy(source,output)
arguments
    source (1,1) string
    output (1,1) string
end
optimizerPath=fullfile(output,'frozen-optimizer/optimizer-summary.json');
optimizer=jsondecode(fileread(optimizerPath));assert(optimizer.passed && optimizer.selected_from_training_only);
assert(jsondecode(fileread(fullfile(output,'learning-rate-tests/learning-rate-test-summary.json'))).passed);
rate=optimizer.selected_learning_rate;assert(rate==1e-5);
contract=struct(optimizer_report_sha256=motorFileSHA256(optimizerPath),critic_learning_rate=rate, ...
    optimizer_selection_used_validation=false,source_manifest_sha256=motorFileSHA256(fullfile(source,'replay/summary.json')), ...
    critic_architecture="local-quadratic",critic_weight_decay=.01,critic_updates_per_candidate=600, ...
    target_tau=.005,target_policy_smoothing_retained=true,seeds=[7 17 27], ...
    original_reward_and_boot_split_preserved=true,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(output,'dynamic-study-contract.json'),contract);studies=struct([]);
for observation=["original","causal"]
    file="audited-input.mat";if observation=="causal",file="causal-input.mat";end
    folder=fullfile(output,"train-"+observation+"-low-rate");
    r=trainMotorFullHallTD3(fullfile(source,file),fullfile(source,'replay'),folder,600, ...
        Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="near-baseline", ...
        ActorGainFeature="masked",RequireMeasuredSwitches=true,ValueCentering=true, ...
        CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=rate, ...
        TrainingSeedMode="isolated-update-stream");
    diagnoseMotorFullHallCritics(fullfile(source,file),string(folder),fullfile(output,"critic-"+observation+"-low-rate.json"));
    diagnoseMotorActorGainDependence(fullfile(source,file),folder,fullfile(output,"gain-dependence-"+observation+"-low-rate.json"));
    row=struct(observation=observation,critic_updates=r.critic_update_iterations,actor_updates=r.actor_updates, ...
        summary_sha256=motorFileSHA256(fullfile(folder,'training-summary.json')));
    if isempty(studies),studies=row;else,studies(end+1)=row;end %#ok<AGROW>
    write(fullfile(output,'dynamic-study-progress.json'),struct(studies=studies));
end
report=struct(passed=true,contract=contract,studies=studies, ...
    critic_update_iterations=sum([studies.critic_updates]),actor_updates=sum([studies.actor_updates]), ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(output,'dynamic-study-summary.json'),report);
end
function write(path,value)
assert(~isfile(path) || endsWith(path,'progress.json'));
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
