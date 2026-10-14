function report=runMotorCompletePairsStudy(root)
arguments
    root (1,1) string
end
data=jsondecode(fileread(fullfile(root,'data-summary.json')));
assert(data.passed && data.all_nine_source_target_pairs_in_both_splits);
contract=struct(unique_physical_windows=data.total_unique_windows,unique_new_physical_windows=data.unique_new_windows, ...
    source_replay_sha256=motorFileSHA256(fullfile(root,'replay/summary.json')), ...
    actual_source_target_gain_pairs_completed=true,actor_gain_features=["masked","observed"], ...
    critic_architecture="local-quadratic",critic_learning_rate=1e-5,critic_weight_decay=.01, ...
    original_reward_including_gain_change_penalty_preserved=true,Ki_fixed=.00144,action_mask=[1 0], ...
    seeds=[7 17 27],critic_iterations_per_candidate=600, ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(root,'training-study-contract.json'),contract);studies=struct([]);
for observation=["original","causal"]
    input="audited-input.mat";if observation=="causal",input="causal-input.mat";end
    for gainFeature=["masked","observed"]
        folder=fullfile(root,"train-"+observation+"-"+gainFeature);
        r=trainMotorFullHallTD3(fullfile(root,input),fullfile(root,'replay'),folder,600, ...
            Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="near-baseline", ...
            ActorGainFeature=gainFeature,RequireMeasuredSwitches=true,ValueCentering=true, ...
            CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5,TrainingSeedMode="isolated-update-stream");
        diagnoseMotorFullHallCritics(fullfile(root,input),string(folder),fullfile(root,"critic-"+observation+"-"+gainFeature+".json"));
        diagnoseMotorActorGainDependence(fullfile(root,input),folder,fullfile(root,"gain-dependence-"+observation+"-"+gainFeature+".json"));
        auditMotorCrossSeedActions(fullfile(root,input),folder,fullfile(root,"cross-seed-"+observation+"-"+gainFeature+".json"));
        row=struct(observation=observation,actor_gain_feature=gainFeature,critic_updates=r.critic_update_iterations, ...
            actor_updates=r.actor_updates,summary_sha256=motorFileSHA256(fullfile(folder,'training-summary.json')));
        if isempty(studies),studies=row;else,studies(end+1)=row;end %#ok<AGROW>
        write(fullfile(root,'training-study-progress.json'),struct(studies=studies));
    end
end
report=struct(passed=true,contract=contract,studies=studies, ...
    critic_update_iterations=sum([studies.critic_updates]),actor_updates=sum([studies.actor_updates]), ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(root,'training-study-summary.json'),report);
end
function write(path,value)
assert(~isfile(path) || endsWith(path,'progress.json'));
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
