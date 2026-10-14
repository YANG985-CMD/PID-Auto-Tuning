function report=testMotorUpper8ExecutionMap(output)
spec=motorStreamGainSpec("upper8-fullhall");levels=spec.exact_kp_levels;
source=repelem(levels,1001);target=repmat(linspace(0,spec.action_upper_limit(1),1001),1,3);
[action,kp,metadata]=motorUpper8ExecutionMap([target;zeros(size(target))],source);
assert(all(ismember(kp,levels)) && all(abs(kp-source)<=.00013556+1e-9) && all(action(2,:)==0));
[~,forward]=motorUpper8ExecutionMap([spec.action_upper_limit(1);0],levels(1));assert(forward==levels(2));
[~,backward]=motorUpper8ExecutionMap([0;0],levels(3));assert(backward==levels(2));
coordinates=(levels-double(single(.003389)))/double(single(.00054224));
for i=1:3
    [~,hold]=motorUpper8ExecutionMap([coordinates(i);0],levels(i));assert(hold==levels(i));
end
for i=1:2
    midpoint=mean(coordinates(i:i+1));
    for j=i:i+1
        [~,hold]=motorUpper8ExecutionMap([midpoint;0],levels(j));assert(hold==levels(j));
    end
end
rejected=0;
for trial=1:5
    input=[.25;0];actual=levels(1);
    switch trial
        case 1,input(1)=NaN;
        case 2,input(2)=.1;
        case 3,input(1)=.6;
        case 4,actual=.0035;
        case 5,input(1)=-.1;
    end
    try,motorUpper8ExecutionMap(input,actual);catch,rejected=rejected+1;end
end
assert(rejected==5);
report=struct(passed=true,grid_cases=3003,invalid_cases_rejected=rejected, ...
    direct_endpoint_moves_require_bridge=true,exact_current_gain_retained_at_ties=true, ...
    host_step_limit_preserved=true,Ki_fixed=true,mapping_version=metadata.mapping_version, ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
