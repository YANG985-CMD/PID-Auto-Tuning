function [loss,g,lambda]=motorTD3ActorLoss(net,critic,x,actionRecorded,scale,valueShift,coordinates,executionMode,executionContract,rlWeight)
% Normalize TD3+BC against the original physical-reward value coordinate.
arguments
    net dlnetwork
    critic dlnetwork
    x
    actionRecorded
    scale
    valueShift (1,1) double {mustBeFinite}
    coordinates (1,1) string {mustBeMember(coordinates,["native","unshifted-physical"])}="unshifted-physical"
    executionMode (1,1) string {mustBeMember(executionMode,["continuous-experimental","upper8-exact-grid-straight-through","upper8-continuous-step-clamp","bidirectional-continuous-step-clamp","bidirectional-feasible-fraction"])}="continuous-experimental"
    executionContract struct=struct
    rlWeight (1,1) double {mustBeNonnegative,mustBeFinite}=25
end
action=forward(net,x);
if executionMode~="continuous-experimental"
    action=motorTD3ExecutedAction(action,x,executionContract,true);
end
q=predict(critic,x,action);
if coordinates=="unshifted-physical",q=q-single(valueShift);end
lambda=rlWeight/max(double(extractdata(mean(abs(q),'all'))),1e-6);
loss=-lambda*mean(q,'all')+mean((scale.*(action-actionRecorded)).^2,'all');
g=dlgradient(loss,net.Learnables);
end
