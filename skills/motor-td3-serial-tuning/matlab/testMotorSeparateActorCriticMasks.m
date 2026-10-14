function report=testMotorSeparateActorCriticMasks(output)
% Mask gain copying in Actor without deleting the Critic's observed PI state.
arguments
    output (1,1) string
end
assert(~isfile(output) && startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
spec=motorStreamGainSpec('lower16-upper4-fullhall');results=struct([]);
for seed=[7 17 27]
    for profile=["history20-40","causal-six-period-Hall-sector-v1"]
        criticMask=ones(10,1);if profile=="history20-40",criticMask(10)=0;end
        actorMask=criticMask;actorMask(8)=0;
        ordinary=createMotorTD3(seed,[1;0],0,ActorInputMask=criticMask,CriticInputMask=criticMask, ...
            ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:),InitialNormalizedAction=[0;0]);
        separate=createMotorTD3(seed,[1;0],0,ActorInputMask=actorMask,CriticInputMask=criticMask, ...
            ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:),InitialNormalizedAction=[0;0]);
        actor=getModel(getActor(separate));x=zeros(10,4,'single');x(3,:)=[-1 -.5 .5 1];changed=x;changed(8,:)=[-5 -1 1 5];
        a=extractdata(predict(actor,dlarray(x,'CB')));b=extractdata(predict(actor,dlarray(changed,'CB')));
        assert(isequal(a,b) && all(a(2,:)==0));
        q1=getCritic(ordinary);q2=getCritic(separate);
        for critic=1:2
            before=getModel(q1(critic));after=getModel(q2(critic));
            assert(isequaln(before.Learnables,after.Learnables));
            assert(criticMask(8)==1 && actorMask(8)==0);
        end
        row=struct(seed=seed,profile=profile,actor_gain_independent=true,critics_unchanged=true,ki_masked=true);
        if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(passed=true,cases=results,hardware_accessed=false,training_performed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
