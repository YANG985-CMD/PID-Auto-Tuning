function report=testMotorCriticLearningRate(input,replay,output)
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
rate=1e-5;decay=.01;
agent=createMotorTD3(7,[1;0],0,CriticLearningRate=rate,CriticL2RegularizationFactor=decay);
for k=1:2
    assert(agent.AgentOptions.CriticOptimizerOptions(k).LearnRate==rate);
    assert(agent.AgentOptions.CriticOptimizerOptions(k).L2RegularizationFactor==decay);
end
invalidRejected=true;
for value=[0 -1 Inf NaN]
    rejected=false;
    try,createMotorTD3(7,[1;0],0,CriticLearningRate=value);catch,rejected=true;end
    invalidRejected=invalidRejected && rejected;
end
assert(invalidRejected);
training=trainMotorFullHallTD3(input,replay,output,2,Sampling="balanced-actual-actions", ...
    RewardModes="complete-Hall",Initialization="near-baseline",ActorGainFeature="masked", ...
    RequireMeasuredSwitches=true,ValueCentering=true,CriticArchitecture="local-quadratic", ...
    CriticWeightDecay=decay,CriticLearningRate=rate,TrainingSeedMode="isolated-update-stream");
assert(training.critic_learning_rate==rate);
for c=training.candidates(:)'
    p=load(fullfile(output,"candidate-complete-Hall-seed-"+c.seed+".mat"),'experimentalAgent','candidateReport');
    assert(c.critic_learning_rate==rate && p.candidateReport.critic_learning_rate==rate);
    assert(p.experimentalAgent.AgentOptions.CriticOptimizerOptions(1).LearnRate==rate);
    assert(p.experimentalAgent.AgentOptions.CriticOptimizerOptions(2).LearnRate==rate);
end
report=struct(passed=true,invalid_rates_rejected=true,critic_learning_rate=rate, ...
    native_options_and_custom_training_report_agree=true,checked_checkpoints=3, ...
    hardware_accessed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'learning-rate-test-summary.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
