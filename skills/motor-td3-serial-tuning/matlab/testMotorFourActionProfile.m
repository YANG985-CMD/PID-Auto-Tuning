function report=testMotorFourActionProfile(replay,input,output)
% Reject new physical actions in the old map and preserve actual slew limits.
arguments
    replay (1,1) string
    input (1,1) string
    output (1,1) string
end
assert(startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/') && ~isfile(output));
s=load(input);assert(s.fullHallAudit.passed);
source=jsondecode(fileread(fullfile(replay,'summary.json')));
new=motorStreamGainSpec('lower16-upper4-fullhall');old=motorStreamGainSpec('lower16-fullhall');
assert(new.action_lower_limit(1)==old.action_lower_limit(1));
assert(new.action_upper_limit(1)>0 && new.action_upper_limit(1)<.251);
assert(isequal(s.fullHallContract.physical_single_step_limit,[.00027112 .000144]));
assert(isequal(new.action_mask,[1 0]) && new.fixed_ki==double(single(.00144)));
counts=zeros(1,4);positiveFound=false;tamperedRejected=false;oldRejected=false;
for item=source.input_manifest(:)'
    w=jsondecode(fileread(item.file));[e,~]=motorLiveWindowExperience(w,s.fullHallContract);
    level=find(new.exact_kp_levels==w.action_applied(1));assert(isscalar(level));counts(level)=counts(level)+1;
    expected=(w.action_applied(1)-s.fullHallContract.encoded_baseline_gains(1))/s.fullHallContract.gain_step_scale(1);
    assert(abs(double(e.Action{1}(1))-expected)<1e-6 && e.Action{1}(2)==0);
    if level==4 && ~positiveFound
        previous=s.fullHallContract;previous.stream_gain_profile="lower16-fullhall";
        try,motorLiveWindowExperience(w,previous);catch err,oldRejected=strcmp(err.identifier,'MATLAB:assertion:failed');end
        bad=w;bad.action_applied(1)=double(single(.00345678));
        for command=1:numel(bad.commands),bad.commands(command).kp=bad.action_applied(1);end
        try,motorLiveWindowExperience(bad,s.fullHallContract);catch err,tamperedRejected=strcmp(err.identifier,'MATLAB:assertion:failed');end
        positiveFound=true;
    end
end
assert(all(counts>=64) && positiveFound && oldRejected && tamperedRejected);
for seed=[7 17 27]
    initial=createMotorTD3(seed,[1;0],0,ActionLowerLimit=new.action_lower_limit(:), ...
        ActionUpperLimit=new.action_upper_limit(:),InitialNormalizedAction=[0;0]);
    actor=getModel(getActor(initial));
    zeroAction=double(extractdata(predict(actor,dlarray(zeros(10,1,'single'),'CB'))));
    assert(abs(zeroAction(1))<1e-6 && zeroAction(2)==0);
    x=dlarray(repmat(single([-5;5]),5,8),'CB');actions=double(extractdata(predict(actor,x)));
    assert(all(actions(1,:)>=new.action_lower_limit(1) & actions(1,:)<=new.action_upper_limit(1)) && all(actions(2,:)==0));
end
report=struct(passed=true,unique_windows=sum(counts),actual_action_counts=counts, ...
    actual_action_mapping_verified=true,old_profile_rejected_positive_action=oldRejected, ...
    altered_actual_gain_rejected=tamperedRejected,baseline_initial_action_verified_for_three_seeds=true, ...
    physical_step_limit_unchanged=true,ki_masked=true,hardware_accessed=false,deployment_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
