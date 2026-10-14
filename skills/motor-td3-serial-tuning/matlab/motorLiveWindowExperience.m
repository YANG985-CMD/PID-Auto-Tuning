function [e,key]=motorLiveWindowExperience(r,contract)
% Audit actual rolling window; advisory predictions never enter these actions.
assert(r.schema_version==1 && string(r.source)=="real_motor_live_actual_ack");
assert(~r.actor_applied && ~r.terminated && ~r.truncated && r.session_shutdown_pending);
assert(~r.deployment_allowed && ~r.performance_claim_allowed);
assert(string(contract.action_coordinates)=="absolute-target");
assert(string(contract.observation_profile)=="history20-40" && string(contract.learning_task)=="continuing");
assert(isequal(contract.action_mask,[1 0]));
s=r.state;h=r.state_history;z=r.response;p=r.response_stage_proofs;c=r.commands;
assert(numel(h)==3 && numel(z)>=4 && numel(p)==numel(z));
assert(isequal(h(end),s));
allPackets=[h(:);z(:)];
assert(all(string({allPackets.boot_id})==string(r.boot_id)));
assert(all([allPackets.enabled]) && all([allPackets.fault]==0));
assert(all(diff([h.seq])==1) && all(diff([z.seq])==1));
for packets={h,z}
    dt=diff([packets{1}.t_us]);assert(all(dt>=15000 & dt<=25000));
end
assert(z(1).seq>s.seq && z(1).t_us>s.t_us && z(end).t_us-z(1).t_us>=60000);
for t=allPackets(:)'
    values=raw(t);assert(all(isfinite(values)));
    assert(abs(t.speed)<1800 && t.current>=0 && t.current<2 && t.vbus>=18 && t.vbus<=30);
    assert(double(single(t.ki))==double(single(.00144)));
end
stage(r.source_stage_proof,s);
first=c([c.command_seq]==r.first_command_seq);assert(isscalar(first));
assert(first.source_t_us==s.t_us && first.expires_us==s.t_us+100000);
assert(isequal(r.action_applied(:)',[first.kp first.ki]));
allowed=[.003389 .00352456];
if isfield(contract,'stream_gain_profile')
    spec=motorStreamGainSpec(string(contract.stream_gain_profile));allowed=spec.exact_kp_levels;
end
assert(any(double(single(first.kp))==double(single(allowed))));
assert(double(single(first.ki))==double(single(.00144)));
for k=1:numel(z)
    t=z(k);stage(p(k),t);cmd=c([c.command_seq]==t.applied_seq);assert(isscalar(cmd));
    assert(t.applied_seq>=first.command_seq && cmd.kp==t.kp && cmd.ki==t.ki);
    assert(cmd.source_t_us<=t.t_apply_us && t.t_apply_us<=cmd.expires_us);
    assert(isequal([t.kp t.ki],r.action_applied(:)'));
end
if isequal([s.kp s.ki],r.action_applied(:)'),effective=s.t_us;
else,effective=z(1).t_apply_us;end
assert(r.t_effective_us==effective && all([z.t_us]>effective));
physicalDelta=[(first.kp-s.kp)/.00027112 0];
assert(max(abs(physicalDelta(:)-r.physical_delta_action(:)))<1e-12);
times=[z.t_us];errors=[z.speed_ref]-[z.speed];dt=diff(times);
mse=sum(.5*(errors(1:end-1).^2+errors(2:end).^2).*dt)/(times(end)-times(1));
current=max([z.current]);speed=max(abs([z.speed]));sat=double([z.current]>=1.98);
saturation=sum(.5*(sat(1:end-1)+sat(2:end)).*dt)/(times(end)-times(1));
reward=-mse/1e6-.12*(current/2)^2-.08*max(0,(speed-1500)/300)^2-.1*saturation-.005*sum(physicalDelta.^2);
assert(abs(r.reward-reward)<1e-12);
observation=features(h,contract);next=features(z(end-2:end),contract);
action=(r.action_applied(:)-contract.encoded_baseline_gains(:))./contract.gain_step_scale(:);
lower=0;upper=.5;
if isfield(contract,'stream_gain_profile')
    spec=motorStreamGainSpec(string(contract.stream_gain_profile));
    lower=spec.action_lower_limit(1);upper=spec.action_upper_limit(1);
end
assert(action(1)>=lower-1e-6 && action(1)<=upper+1e-6 && action(2)==0);
e=struct('Observation',{{single(observation)}},'Action',{{single(action)}}, ...
    'Reward',reward,'NextObservation',{{single(next)}},'IsDone',0);
key=string(r.boot_id)+":"+string(r.first_command_seq)+":"+string(z(end).seq);
end

function stage(p,t)
assert(p.started==1 && p.run_seen==1 && p.fault==0 && p.irq_fault==0);
assert(p.started_us<=p.run_started_us && p.run_started_us<=t.t_us && t.t_us<=p.last_us);
assert(abs((t.t_us-p.started_us)/1000-t.elapsed_ms)<=2);
end

function x=features(h,c)
t=h(end);x=raw(t)./[1000 1000 1000 1000 3 2 24 .003389 .00144 3000];
x(4)=(h(end-1).speed_ref-h(end-1).speed)/1000;
x(9)=(h(end-2).speed_ref-h(end-2).speed)/1000;
x=double(single(max(-5,min(5,x))));
x=max(-5,min(5,(x(:)-c.state_center(:))./c.state_scale(:)));
end

function x=raw(t)
x=[t.speed_ref t.speed t.speed_ref-t.speed t.error_history t.integral_output ...
    t.current t.vbus t.kp t.ki t.elapsed_ms];
end
