function [action,report]=motorFeasibleFractionAction(raw,observation,contract)
% Internal fraction [-1,1] -> feasible absolute replay/Critic action coordinate.
assert(contract.execution_mode=="bidirectional-feasible-fraction");
assert(contract.actor_raw_coordinates=="feasible-fraction[-1,1]" && contract.critic_action_coordinates=="absolute-target-v7");
if isa(raw,'dlarray'),r=double(extractdata(raw));else,r=double(raw);end
if isa(observation,'dlarray'),x=extractdata(observation);else,x=observation;end
assert(size(r,1)==2 && size(r,2)==size(x,2) && all(isfinite(r),'all') && all(r(2,:)==0));
assert(all(abs(r(1,:))<=1+1e-6));
spec=motorStreamGainSpec(contract.stream_gain_profile);
[~,base]=motorBidirectionalContinuousActionFromObservation(zeros(size(r),'single'),x,contract);
actual=base.actual_kp;encoded=(actual-contract.encoded_baseline_gains(1))/contract.gain_step_scale(1);
step=.00013556/contract.gain_step_scale(1);
lower=max(spec.action_lower_limit(1),encoded-step);upper=min(spec.action_upper_limit(1),encoded+step);
mid=(upper+lower)/2;half=(upper-lower)/2;assert(all(half>0));
if isa(raw,'dlarray')
    first=dlarray(single(mid),'CB')+dlarray(single(half),'CB').*min(1,max(-1,raw(1,:)));
    action=[first;raw(2,:)*0];v=double(extractdata(action));
else
    action=single([mid+half.*min(1,max(-1,r(1,:)));zeros(1,size(r,2))]);v=double(action);
end
kp=double(single(contract.encoded_baseline_gains(1)+contract.gain_step_scale(1)*v(1,:)));
assert(all(abs(kp-actual)<=.00013556+1e-9));
report=struct(actual_kp=actual,executed_float32_kp=kp,lower_absolute_action=lower,upper_absolute_action=upper, ...
    half_feasible_span=half,raw_coordinates="feasible-fraction[-1,1]",output_coordinates="absolute-target-v7", ...
    host_single_kp_step_limit=.00013556,Ki_fixed=.00144,hardware_accessed=false,deployment_allowed=false);
end
