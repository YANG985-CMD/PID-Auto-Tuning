function report=testMotorLower8Support(checkpoint,windows)
% Hardware-free support/mask tests using existing audited real windows.
arguments
    checkpoint (1,1) string
    windows (1,1) string
end
s=load(checkpoint,'contract');c=s.contract;c.stream_gain_profile="lower8";
spec=motorStreamGainSpec("lower8");
assert(isequal(spec.action_mask,[1 0]) && spec.fixed_ki==double(single(.00144)));
assert(isequal(spec.action_lower_limit,[-1 -1]) && isequal(spec.action_upper_limit,[.5 1]));
assert(ismember(double(single(.003121269)),spec.exact_kp_levels));
mask=ones(10,1);mask([8 10])=0;
agent=createMotorTD3(7,[1;0],2.5,ActorInputMask=mask, ...
    ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:), ...
    CriticInitialValue=-.1,CriticL2RegularizationFactor=0);
files=dir(fullfile(windows,'window-*.json'));assert(~isempty(files));
for f=files'
    [e,key]=motorLiveWindowExperience(jsondecode(fileread(fullfile(f.folder,f.name))),c);
    assert(strlength(key)>0);validateExperience(agent.ExperienceBuffer,e);
    append(agent.ExperienceBuffer,e);
end
rng(991);obs=single(rand(10,128)*10-5);changed=obs;changed([8 10],:)=-changed([8 10],:);
actor=getActor(agent);a=getAction(actor,{obs});b=getAction(actor,{changed});
assert(isequal(a{1},b{1}) && all(a{1}(2,:)==0));
assert(all(a{1}(1,:)>=-1 & a{1}(1,:)<=.5));
rejected=false;try,motorStreamGainSpec("unknown");catch,rejected=true;end;assert(rejected);
report=struct(passed=true,existing_real_windows_validated=numel(files), ...
    reloaded_experience_count=agent.ExperienceBuffer.Length,random_mask_checks=128, ...
    new_negative_gain_physically_validated=false,hardware_accessed=false,training_performed=false, ...
    action_mask=[1 0],fixed_ki=.00144,deployment_allowed=false);
disp(jsonencode(report));
end
