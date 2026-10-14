function [executed,rawKp,report]=motorUpper8ExecutionMap(suggestion,actualKp)
% Offline exact-point mapper for the v24 experimental host step contract.
% It has no device access and cannot grant parameter application permission.
arguments
    suggestion (2,:) double
    actualKp (1,:) double
end
assert(size(suggestion,2)==numel(actualKp));
spec=motorStreamGainSpec("upper8-fullhall");levels=spec.exact_kp_levels;
assert(all(isfinite([suggestion(:);actualKp(:)])) && all(suggestion(2,:)==0));
assert(all(suggestion(1,:)>=-1e-6 & suggestion(1,:)<=spec.action_upper_limit(1)+1e-6));
assert(all(ismember(actualKp,levels)),'MotorTD3:ActualGain','Exact actual gain readback required');
u=max(0,min(spec.action_upper_limit(1),suggestion(1,:)));
baseline=double(single(.003389));scale=double(single(.00054224));
coordinates=(levels-baseline)/scale;selected=zeros(1,numel(actualKp));
preferred=baseline+scale*u;bridgeRequired=false(size(selected));
for k=1:numel(actualKp)
    eligible=abs(levels-actualKp(k))<=.00013556+1e-9;
    distances=abs(coordinates-u(k));distances(~eligible)=Inf;
    closest=min(distances);ties=find(abs(distances-closest)<=1e-7);
    assert(~isempty(ties));hold=find(levels==actualKp(k));
    if ismember(hold,ties),index=hold;else,index=ties(1);end
    selected(k)=index;bridgeRequired(k)=abs(preferred(k)-actualKp(k))>.00013556+1e-9;
end
rawKp=levels(selected);executed=[coordinates(selected);zeros(1,numel(selected))];
assert(all(abs(rawKp-actualKp)<=.00013556+1e-9) && all(ismember(rawKp,levels)));
report=struct(mapping_version="upper8-exact-readback-nearest-feasible-hold-ties-v1", ...
    mapped_action_count=numel(actualKp),host_single_kp_step_limit=.00013556, ...
    firmware_single_kp_step_limit=.00027112,requires_bridge_count=sum(bridgeRequired), ...
    exact_readback_required=true,tie_rule="retain actual gain", ...
    continuous_actor_to_discrete_execution_is_policy_change=true, ...
    fixed_ki=.00144,hardware_accessed=false,actor_applied=false,candidate_admission=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
end
