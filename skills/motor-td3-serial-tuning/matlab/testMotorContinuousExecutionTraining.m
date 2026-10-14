function report=testMotorContinuousExecutionTraining(input,replay,output)
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);s=load(input);c=s.fullHallContract;
c.actor_input_mask(8)=1;c.execution_mode="upper8-continuous-step-clamp";
spec=motorStreamGainSpec("upper8-dense-fullhall");actual=spec.exact_kp_levels([1 5 9]);
state=zeros(10,3,'single');state(8,:)=single((actual/.003389-c.state_center(8))/c.state_scale(8));
raw=single([.49 .26 .01;0 0 0]);
[plain,meta]=motorUpper8ContinuousActionFromObservation(raw,state,c);
[a,g]=dlfeval(@gradientCheck,dlarray(raw,'CB'),dlarray(state,'CB'),c);
assert(max(abs(double(extractdata(a)-plain)),[],'all')<1e-7);
assert(isequal(extractdata(g(1,:)),single([0 1 0])) && all(extractdata(g(2,:))==0));
plus=motorUpper8ContinuousActionFromObservation(raw+single([1e-4 1e-4 1e-4;0 0 0]),state,c);
assert(abs(double(plus(1,2)-plain(1,2))-1e-4)<1e-7);
assert(plain(1,1)==plus(1,1) && plain(1,3)==plus(1,3));
assert(~meta.nearest_grid_quantization && ~meta.straight_through_surrogate_used);
badState=state;badState(8,1)=100;rejects=0;
for pair={struct(raw=raw,x=badState),struct(raw=single([.2;.1]),x=state(:,1)), ...
        struct(raw=single([NaN;0]),x=state(:,1))}
    p=pair{1};try,motorUpper8ContinuousActionFromObservation(p.raw,p.x,c);catch,rejects=rejects+1;end
end
assert(rejects==3);
training=trainMotorFullHallTD3(input,replay,fullfile(output,'training'),2, ...
    Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="range-midpoint", ...
    ActorGainFeature="observed",RequireMeasuredSwitches=true,ValueCentering=true, ...
    CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5, ...
    TrainingSeedMode="isolated-update-stream",CriticInitialization="factual-ridge-bootstrap", ...
    ExecutionMode="upper8-continuous-step-clamp");
for row=training.candidates(:)'
    assert(row.execution_wrapper_required && row.target_action_samples==64);
    assert(row.target_smoothing_executed_action_changes>0);
    p=load(fullfile(output,'training',"candidate-complete-Hall-seed-"+row.seed+".mat"),'contract');
    assert(~p.contract.straight_through_gradient_is_experimental_surrogate && ~p.contract.runtime_compatible);
    assert(~row.candidate_admission && ~row.deployment_allowed && row.fixed_ki==.00144);
end
report=struct(passed=true,finite_difference_and_gradient_checked=true,exact_clamp_derivative_in_open_regions=true, ...
    no_nearest_grid_quantization=true,no_straight_through_surrogate=true,invalid_observations_rejected=rejects, ...
    replay_target_loss_and_evaluation_share_execution_map=true,target_noise_changes_executed_actions=true, ...
    test_only_critic_update_iterations=6,test_only_actor_updates=3,checked_checkpoints=3, ...
    hardware_accessed=false,actor_applied=false,Ki_fixed=.00144,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'continuous-execution-tests.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function [a,g]=gradientCheck(raw,x,c)
a=motorTD3ExecutedAction(raw,x,c,true);loss=sum(a(1,:),'all');g=dlgradient(loss,raw);
end
