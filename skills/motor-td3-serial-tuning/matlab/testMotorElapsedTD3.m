function result=testMotorElapsedTD3(replay,checkpoint)
% Real decision audit + independent target algebra; no learning or hardware.
arguments
    replay (1,1) string
    checkpoint (1,1) string
end
summary=jsondecode(fileread(fullfile(replay,'summary.json')));
assert(summary.total_unique_decisions==90 && ~summary.old_short_windows_also_appended);
s=load(checkpoint,'contract');c=s.contract;c.stream_gain_profile="lower8-sampling";
last=containers.Map('KeyType','char','ValueType','any');keys=strings(0,1);
for record=summary.input_manifest(:)'
    assert(motorFileSHA256(record.file)==string(record.sha256));r=jsondecode(fileread(record.file));
    [e,key]=motorLiveWindowExperience(r,c);assert(~any(keys==key));keys(end+1)=key; %#ok<AGROW>
    assert(r.duration_us==r.response(end).t_us-r.state.t_us);
    assert(abs(r.elapsed_discount-.99^(r.duration_us/100000))<1e-12);
    assert(r.measured_reward_span_us==r.response(end).t_us-r.response(1).t_us);
    assert(r.unscored_pre_application_and_sample_latency_us==r.duration_us-r.measured_reward_span_us);
    t=double([r.response.t_us]);err=[r.response.speed_ref]-[r.response.speed];
    meanSquare=trapz(t,err.^2)/(t(end)-t(1));peakCurrent=max([r.response.current]);
    peakSpeed=max([r.response.speed]);sat=trapz(t,double([r.response.current]>=1.98))/(t(end)-t(1));
    rate=-meanSquare/1e6-.3*(peakCurrent/2)^2-.25*max(0,(peakSpeed-1500)/300)^2-.25*sat;
    expectedReward=rate*(t(end)-t(1))/100000-.0005*r.physical_delta_action(1)^2;
    assert(abs(expectedReward-r.time_scaled_reward)<1e-12);
    boot=char(r.boot_id);if isKey(last,boot),assert(isequal(last(boot),r.state));end
    last(boot)=r.response(end);assert(e.IsDone==0);
end
r=[1 2 -3];q1=[4 5 6];q2=[7 3 2];duration=[100000 400000 450000];done=[0 1 0];
y=motorElapsedTD3Target(r,q1,q2,duration,done);
expected=single([1+.99*4 2 -3+.99^4.5*2]);assert(isequal(y,expected));
assert(isequal(motorElapsedTD3Target(r,q1,q2,ones(1,3)*100000,zeros(1,3)),single(r+.99*min(q1,q2))));
reject(@()motorElapsedTD3Target(r,q1,q2,[100000 0 450000],done));
reject(@()motorElapsedTD3Target(r,q1,q2,duration,[0 .5 0]));
result=struct(passed=true,real_decisions_audited=90,target_checks=4,independent_reward_checks=90, ...
    linked_states_passed=true,hardware_accessed=false,training_performed=false);
disp(jsonencode(result));
end
function reject(f)
failed=false;try,f();catch,failed=true;end;assert(failed);
end
