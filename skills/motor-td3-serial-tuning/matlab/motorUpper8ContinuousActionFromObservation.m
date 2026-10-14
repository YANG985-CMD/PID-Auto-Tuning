function [action,report]=motorUpper8ContinuousActionFromObservation(suggestion,observation,contract)
% Continuous magnitude/rate clipping. No nearest-grid quantization or STE.
arguments
    suggestion
    observation
    contract struct
end
assert(string(contract.stream_gain_profile)=="upper8-dense-fullhall");
assert(isequal(contract.action_mask,[1 0]) && contract.actor_input_mask(8)==1);
if isa(suggestion,'dlarray'),raw=double(extractdata(suggestion));else,raw=double(suggestion);end
if isa(observation,'dlarray'),x=double(extractdata(observation));else,x=double(observation);end
assert(size(x,1)==10 && size(raw,1)==2 && size(x,2)==size(raw,2));
spec=motorStreamGainSpec("upper8-dense-fullhall");
assert(all(isfinite(x),'all') && all(isfinite(raw),'all') && all(raw(2,:)==0));
assert(all(raw(1,:)>=spec.action_lower_limit(1)-1e-6 & raw(1,:)<=spec.action_upper_limit(1)+1e-6));
actual=.003389*(x(8,:)*contract.state_scale(8)+contract.state_center(8));
assert(all(actual>=spec.exact_kp_levels(1)-1e-9 & actual<=spec.exact_kp_levels(end)+1e-9), ...
    'MotorTD3:ActualGain','Actual observed Kp outside the declared continuous interval');
actual=max(spec.exact_kp_levels(1),min(spec.exact_kp_levels(end),actual));
encoded=(actual-contract.encoded_baseline_gains(1))/contract.gain_step_scale(1);
step=.00013556/contract.gain_step_scale(1);
lower=max(spec.action_lower_limit(1),encoded-step);
upper=min(spec.action_upper_limit(1),encoded+step);
if isa(suggestion,'dlarray')
    first=min(max(suggestion(1,:),dlarray(single(lower),'CB')),dlarray(single(upper),'CB'));
    action=[first;suggestion(2,:)*0];
else
    action=single([min(max(raw(1,:),lower),upper);zeros(1,size(raw,2))]);
end
if isa(action,'dlarray'),executed=double(extractdata(action));else,executed=double(action);end
kp=double(single(contract.encoded_baseline_gains(1)+contract.gain_step_scale(1)*executed(1,:)));
assert(all(abs(kp-actual)<=.00013556+1e-9));
report=struct(mapping_version="upper8-continuous-relative-step-clamp-v1", ...
    actual_kp=actual,executed_float32_kp=kp,Ki_fixed=.00144,nearest_grid_quantization=false, ...
    straight_through_surrogate_used=false,host_single_kp_step_limit=.00013556, ...
    hardware_accessed=false,actor_applied=false,deployment_allowed=false);
end
