function report=testMotorTD3ActionSupport()
% Agent and Actor both constrain Kp to measured baseline/+4% support.
agent=createMotorTD3(7,[1;0],.25,ActionLowerLimit=[0;-1],ActionUpperLimit=[.5;1]);
info=getActionInfo(agent);
assert(isequal(info.LowerLimit,[0;-1]) && isequal(info.UpperLimit,[.5;1]));
x=single(repmat(linspace(-5,5,81),10,1));
a=getAction(getActor(agent),{x});a=double(a{1});
assert(all(a(1,:)>=0 & a(1,:)<=.5) && all(a(2,:)==0));
agent.UseExplorationPolicy=true;
for k=1:100
    b=getAction(agent,{x(:,1+mod(k,81))});
    assert(b{1}(1)>=0 && b{1}(1)<=.5 && b{1}(2)==0);
end
badRejected=false;
try
    createMotorTD3(7,[1;0],.25,ActionLowerLimit=[.6;-1],ActionUpperLimit=[.5;1]);
catch
    badRejected=true;
end
assert(badRejected);
report=struct(passed=true,actor_support_checked=true,agent_action_clipping_checked=true, ...
    fixed_ki_preserved=true,invalid_support_rejected=true,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
end
