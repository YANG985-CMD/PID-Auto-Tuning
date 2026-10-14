function report=testMotorFullIntervalProfile(input,replay,output)
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);rejected=false;
try
    trainMotorFullHallTD3(input,replay,fullfile(output,'rejected-ambiguous-profile'),2);
catch err
    rejected=strcmp(err.identifier,'MotorTD3:RewardProfile');
end
assert(rejected && isempty(dir(fullfile(output,'rejected-ambiguous-profile','*.mat'))));
folder=fullfile(output,'explicit-full-profile');
r=trainMotorFullHallTD3(input,replay,folder,2,Sampling="balanced-actual-actions", ...
    RewardModes="complete-Hall",Initialization="near-baseline",ActorGainFeature="observed", ...
    RequireMeasuredSwitches=true,ValueCentering=true,CriticArchitecture="local-quadratic", ...
    CriticWeightDecay=.01,CriticLearningRate=1e-5,TrainingSeedMode="isolated-update-stream");
assert(string(r.learning_reward_profile)=="full-decision-observed-latency-v1");
assert(~r.original_physical_rewards_unchanged && r.raw_recorded_rewards_unchanged);
for c=r.candidates(:)'
    path=fullfile(folder,"candidate-complete-Hall-seed-"+c.seed+".mat");s=load(path,'contract');
    assert(isequal(c.action_mask,[1 0]) && ~c.original_physical_rewards_unchanged);
    assert(~s.contract.original_physical_rewards_unchanged && s.contract.raw_recorded_rewards_unchanged);
    assert(s.contract.post_ack_reward_retained && s.contract.actor_input_mask(8)==1);
end
d=diagnoseMotorFullHallCritics(input,string(folder),fullfile(output,'diagnostic-Q-coordinates.json'));
assert(all(contains(string({d.results.Q_value_report_coordinates}),"full-decision-observed-latency-v1")));
report=struct(passed=true,ambiguous_reward_modes_rejected=true,changed_learning_reward_labeled=true, ...
    raw_rewards_preserved_and_Ki_mask_verified=true,full_reward_Q_coordinates_labeled=true, ...
    diagnostic_gradient_iterations=6,diagnostic_actor_updates=3,hardware_accessed=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'profile-test-summary.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
