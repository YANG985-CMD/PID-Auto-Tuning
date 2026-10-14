function report=testMotorValueMetadata(input,replay,output)
% Verify the real initializer metadata; legacy audit values are not reused.
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
assert(~isfolder(output) && startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
training=trainMotorFullHallTD3(input,replay,output,2,Sampling="balanced-actual-actions", ...
    RewardModes="complete-Hall",Initialization="near-baseline",ActorGainFeature="masked", ...
    RequireMeasuredSwitches=true,ValueCentering=true);
assert(~isfield(training.learning_contract,'critic_initial_value'));
s=load(input);r=single(cellfun(@(v)v.reward,s.fullHallTrain)');
dt=cellfun(@(v)v.duration_us,s.fullHallTrain)';g=.99.^(dt/100000);
C=-mean(double(r))/(1-mean(g));
expected=mean(double(single(double(r)+C*(1-g))))/(1-mean(g));
for c=training.candidates(:)'
    checkpoint=load(fullfile(output,"candidate-complete-Hall-seed-"+c.seed+".mat"),'contract','candidateReport');
    assert(c.critic_initial_value==expected && checkpoint.contract.critic_initial_value==expected);
    assert(c.critic_value_shift_C==C && checkpoint.contract.q_value_shift==C);
end
report=struct(passed=true,checked_candidate_initializers=numel(training.candidates), ...
    inherited_critic_initial_value_not_used=true,expected_centered_initial_value=expected, ...
    no_performance_candidate_admission=true,hardware_accessed=false,deployment_allowed=false);
f=fopen(fullfile(output,'metadata-test-summary.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
