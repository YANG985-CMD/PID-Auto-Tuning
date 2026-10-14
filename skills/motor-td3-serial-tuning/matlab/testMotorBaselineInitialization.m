function report=testMotorBaselineInitialization(output)
% Optional one-sided baseline start; default construction remains reproducible.
arguments
    output (1,1) string
end
assert(startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
assert(~isfile(output));spec=motorStreamGainSpec('lower16-fullhall');rows=struct([]);
for seed=[7 17 27]
    default=createMotorTD3(seed,[1;0],0,ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:));
    explicit=createMotorTD3(seed,[1;0],0,ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:),InitialNormalizedAction=NaN(2,1));
    near=createMotorTD3(seed,[1;0],0,ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:),InitialNormalizedAction=[0;0]);
    a=getModel(getActor(default));b=getModel(getActor(explicit));n=getModel(getActor(near));
    assert(isequaln(a.Learnables,b.Learnables));
    ca=getCritic(default);cb=getCritic(explicit);cn=getCritic(near);
    for critic=1:2
        qa=getModel(ca(critic));qb=getModel(cb(critic));qn=getModel(cn(critic));
        assert(isequaln(qa.Learnables,qb.Learnables) && isequaln(qa.Learnables,qn.Learnables));
    end
    x=dlarray(single([zeros(10,1) repmat([5;-5],5,1)]),'CB');
    old=double(extractdata(predict(a,x)));new=double(extractdata(predict(n,x)));
    assert(all(new(1,:)>=spec.action_lower_limit(1) & new(1,:)<=0) && all(new(2,:)==0));
    assert(abs(new(1,1))<.01 && abs(old(1,1)-spec.action_lower_limit(1)/2)<1e-6);
    row=struct(seed=seed,default_zero_input=old(:,1),near_baseline_zero_input=new(:,1), ...
        legacy_default_actor_and_critics_unchanged=true,near_baseline_critics_unchanged=true);
    if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
end
rejected=false;
try
    createMotorTD3(7,[1;0],0,ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:),InitialNormalizedAction=[.1;0]);
catch err
    rejected=strcmp(err.identifier,'MATLAB:assertion:failed');
end
assert(rejected);
report=struct(passed=true,seeds=rows,out_of_range_initial_action_rejected=rejected, ...
    hardware_accessed=false,training_performed=false,deployment_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
