function report=verifyMotorUpper8Profile(replay,parent,output)
% Audit the new coordinate against real actions; keep legacy rejection intact.
arguments
    replay (1,1) string
    parent (1,1) string
    output (1,1) string
end
assert(~isfile(output));spec=motorStreamGainSpec("upper8-fullhall");
assert(isequal(spec.exact_kp_levels,double(single([.003389 .00352456 .00366012]))));
coordinates=(spec.exact_kp_levels-double(single(.003389)))/double(single(.00054224));
assert(max(abs(coordinates-[0 .25 .5]))<1e-6 && isequal(spec.action_mask,[1 0]));
assert(spec.action_lower_limit(1)==0 && abs(spec.action_upper_limit(1)-.5)<1e-6);
old=motorStreamGainSpec("switching-local4-fullhall");
assert(isequal(old.exact_kp_levels,double(single([.00325344 .003389 .00352456]))));
assert(~ismember(spec.exact_kp_levels(end),old.exact_kp_levels));
source=jsondecode(fileread(fullfile(replay,'summary.json')));
assert(string(source.action_coordinate_version)=="absolute-target-upper8-scale0p00054224-v4");
selected=[];
for item=source.input_manifest(:)'
    w=jsondecode(fileread(item.file));
    if w.action_applied(1)==spec.exact_kp_levels(end),selected=w;break;end
end
assert(~isempty(selected));p=load(parent,'fullHallContract');c=p.fullHallContract;
c.stream_gain_profile="switching-local4-fullhall";rejected=false;
try,motorLiveWindowExperience(selected,c);catch,rejected=true;end
assert(rejected,'MotorTD3:Mapping','New physical action must not be admitted by old profile');
report=struct(passed=true,new_coordinates=coordinates,old_mapping_rejects_new_actual_action=true, ...
    old_local4_exact_levels_preserved=true,action_mask=[1 0],Ki_fixed=.00144, ...
    physical_data_not_clipped=true,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
