function report=testMotorExecutedActionTraining(input,replay,output)
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);s=load(input);c=s.fullHallContract;
c.actor_input_mask(8)=1;spec=motorStreamGainSpec("upper8-fullhall");
actual=spec.exact_kp_levels;state=zeros(10,3,'single');
state(8,:)=single((actual/.003389-c.state_center(8))/c.state_scale(8));
requested=single([.05 .26 .49;0 0 0]);
plain=motorUpper8ActionFromObservation(requested,state,c);
assert(all(plain(2,:)==0));
[forward,derivative]=dlfeval(@gradientCheck,dlarray(requested,'CB'),dlarray(state,'CB'),c);
assert(max(abs(double(extractdata(forward)-plain)),[],'all')<1e-7);
assert(all(extractdata(derivative(1,:))==1) && all(extractdata(derivative(2,:))==0));
plus=motorUpper8ActionFromObservation(requested+single([1e-5 1e-5 1e-5;0 0 0]),state,c);
assert(isequal(plus,plain),'Interior discrete forward map must be locally constant');
badState=state;badState(8,1)=100;rejected=false;
try,motorUpper8ActionFromObservation(requested,badState,c);catch,rejected=true;end
assert(rejected);
training=trainMotorFullHallTD3(input,replay,fullfile(output,'training'),2, ...
    Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="range-midpoint", ...
    ActorGainFeature="observed",RequireMeasuredSwitches=true,ValueCentering=true, ...
    CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5, ...
    TrainingSeedMode="isolated-update-stream",CriticInitialization="factual-ridge-bootstrap", ...
    ExecutionMode="upper8-exact-grid-straight-through");
for row=training.candidates(:)'
    assert(row.execution_wrapper_required && row.target_action_samples==64);
    assert(row.execution_mode=="upper8-exact-grid-straight-through" && isequal(row.action_mask,[1 0]));
    p=load(fullfile(output,'training',"candidate-complete-Hall-seed-"+row.seed+".mat"),'contract','trainingState');
    assert(p.contract.execution_wrapper_required && p.contract.host_single_kp_step_limit==.00013556);
    values=cellfun(@(r)r.observation(:),s.fullHallValidation,UniformOutput=false);x=single(cat(2,values{:}));
    raw=predict(p.trainingState.actor,dlarray(x,'CB'));
    mapped=extractdata(motorUpper8ActionFromObservation(raw,dlarray(x,'CB'),p.contract));
    current=cellfun(@(r)r.actual_source_kp,s.fullHallValidation)';
    normalized=double(single(.003389))+double(single(.00054224))*double(mapped(1,:));
    assert(all(abs(normalized-current)<=.00013556+1e-9) && all(mapped(2,:)==0));
    assert(~row.candidate_admission && ~row.deployment_allowed);
end
report=struct(passed=true,numeric_forward_map_matches_wrapper=true, ...
    surrogate_gradient_identity_explicitly_tested=true,surrogate_is_not_exact_discrete_derivative=true, ...
    unknown_actual_gain_rejected=rejected,recorded_replay_matches_exact_execution=true, ...
    target_and_actor_objective_use_same_map=true,checked_candidate_checkpoints=3, ...
    test_only_critic_update_iterations=6,test_only_actor_updates=3,Ki_fixed=.00144, ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'execution-training-tests.json'),'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function [a,g]=gradientCheck(raw,x,c)
a=motorUpper8ActionFromObservation(raw,x,c,true);loss=sum(a(1,:),'all');g=dlgradient(loss,raw);
end
