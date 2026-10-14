function report=testMotorCriticInitialization(dataset)
% Check backward compatibility and fixed-Ki / value-prior contracts.
arguments
    dataset (1,1) string
end
physical=validateSpeedLoopResponseReplay(dataset,[1;0]);
initial=mean(cellfun(@(r)r.reward,physical.train))/(1-.99);
a=createMotorTD3(7,[1;0],.25);
b=createMotorTD3(7,[1;0],.25,CriticInitialValue=NaN);
ca=getCritic(a);cb=getCritic(b);
for k=1:2
    x=getModel(ca(k));y=getModel(cb(k));
    for j=1:height(x.Learnables)
        assert(isequal(extractdata(x.Learnables.Value{j}),extractdata(y.Learnables.Value{j})));
    end
end
values=zeros(3,2);seeds=[7 17 27];
for k=1:3
    agent=createMotorTD3(seeds(k),[1;0],.25,CriticInitialValue=initial);
    critics=getCritic(agent);
    for j=1:2
        values(k,j)=getValue(critics(j),{single(physical.train{1}.observation(:))},{single([0;0])});
    end
    action=getAction(getActor(agent),{single(physical.train{1}.observation(:))});
    assert(action{1}(2)==0);
end
assert(all(isfinite(values),'all') && all(abs(values-initial)<.03,'all'));
report=struct(passed=true,legacy_initialization_unchanged=true,ki_mask_preserved=true, ...
    initial_value=initial,critic_outputs=values,hardware_accessed=false);
end
