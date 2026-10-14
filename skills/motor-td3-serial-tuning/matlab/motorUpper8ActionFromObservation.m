function [action,report]=motorUpper8ActionFromObservation(suggestion,observation,contract,straightThrough)
% Forward uses exact allowed points; straight-through gradients are a
% surrogate for discrete execution, not exact derivatives of the map.
arguments
    suggestion
    observation
    contract struct
    straightThrough (1,1) logical=false
end
assert(string(contract.stream_gain_profile)=="upper8-fullhall");
assert(isequal(contract.action_mask,[1 0]) && contract.actor_input_mask(8)==1);
if isa(suggestion,'dlarray'),raw=double(extractdata(suggestion));else,raw=double(suggestion);end
if isa(observation,'dlarray'),x=double(extractdata(observation));else,x=double(observation);end
assert(size(x,1)==10 && size(raw,1)==2 && size(x,2)==size(raw,2));
spec=motorStreamGainSpec("upper8-fullhall");
observed=.003389*(x(8,:)*contract.state_scale(8)+contract.state_center(8));
[distance,index]=min(abs(spec.exact_kp_levels(:)-observed),[],1);
assert(all(distance<1e-9),'MotorTD3:ActualGain','Observation does not encode an audited actual gain');
actual=spec.exact_kp_levels(index);
[executed,~,report]=motorUpper8ExecutionMap(raw,actual);
if isa(suggestion,'dlarray')
    if straightThrough
        action=suggestion+dlarray(single(executed)-extractdata(suggestion),'CB');
    else,action=dlarray(single(executed),'CB');end
else,action=single(executed);end
report.straight_through_surrogate_used=straightThrough;
report.original_suggestion_preserved_as_advisory=true;
end
