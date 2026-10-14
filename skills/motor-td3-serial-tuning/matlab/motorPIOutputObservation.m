function x=motorPIOutputObservation(h,c)
% Version-specific inference input; never apply this to the old clock contract.
assert(string(c.observation_profile)=="history20-40-PI-command-v1");
assert(numel(h)==3 && isequal(c.action_mask,[1 0]));
assert(all([h.enabled]) && all([h.fault]==0) && all([h.ki]==double(single(.00144))));
assert(all(diff([h.seq])==1) && all(diff([h.t_us])>=15000 & diff([h.t_us])<=25000));
assert(numel(unique(string({h.boot_id})))==1 && c.actor_input_mask(10)==1);
t=h(end);
values=[t.speed_ref,t.speed,t.speed_ref-t.speed,h(end-1).speed_ref-h(end-1).speed, ...
    t.integral_output,t.current,t.vbus,t.kp,h(end-2).speed_ref-h(end-2).speed,0];
assert(all(isfinite(values)) && isfinite(t.error_history));
engineering=[1000,1000,1000,1000,3,2,24,.003389,1000,3];
raw=double(single(max(-5,min(5,values./engineering))));
iq=min(single(3),max(single(-3),single(t.kp)*single(t.error_history)+single(t.integral_output)));
raw(10)=double(single(iq/single(3)));
x=single(max(-5,min(5,(raw(:)-c.state_center(:))./c.state_scale(:))));
end
