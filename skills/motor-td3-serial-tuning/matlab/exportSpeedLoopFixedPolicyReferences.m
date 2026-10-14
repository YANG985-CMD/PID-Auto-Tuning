function report=exportSpeedLoopFixedPolicyReferences(checkpoint,trial,output)
% Frozen Actor + explicit experimental discrete mapping, advisory only.
arguments
    checkpoint (1,1) string
    trial (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);
s=load(checkpoint,'experimentalAgent','contract');c=s.contract;
assert(isequal(c.action_mask,[1 0]) && string(c.observation_profile)=="history20-40");
levels=[0 .25 .5];
if isfield(c,'stream_gain_profile') && string(c.stream_gain_profile)=="lower4"
    assert(c.lower_commission_learning_initialized);levels=[-.5 levels];
elseif isfield(c,'stream_gain_profile') && string(c.stream_gain_profile)=="lower8"
    assert(c.lower8_learning_initialized);
    levels=[(double(single(.003121269))-double(single(.003389)))/.00027112 -.5 levels];
elseif isfield(c,'stream_gain_profile') && string(c.stream_gain_profile)=="lower8-sampling"
    assert(c.older_fixed_cadence_replay_excluded);
    levels=[(double(single(.003121269))-double(single(.003389)))/.00027112 -.5 0];
end
thresholds=(levels(1:end-1)+levels(2:end))/2;
raw=cellfun(@jsondecode,cellstr(splitlines(strtrim(fileread(fullfile(trial,'telemetry.jsonl'))))),UniformOutput=false);
packets=[raw{:}];vectors=cell(0,1);actor=getActor(s.experimentalAgent);
for k=3:numel(packets)
    h=packets(k-2:k);
    if ~all([h.enabled]) || h(end).elapsed_ms<3850 || h(end).elapsed_ms>=23700,continue;end
    assert(all(diff([h.seq])==1) && all(diff([h.t_us])>=15000 & diff([h.t_us])<=25000));
    t=h(end);state=[t.speed_ref t.speed t.speed_ref-t.speed t.error_history t.integral_output t.current t.vbus t.kp t.ki t.elapsed_ms];
    x=state./[1000 1000 1000 1000 3 2 24 .003389 .00144 3000];
    x(4)=(h(end-1).speed_ref-h(end-1).speed)/1000;
    x(9)=(h(end-2).speed_ref-h(end-2).speed)/1000;
    x=double(single(max(-5,min(5,x))));
    observation=single(max(-5,min(5,(x(:)-c.state_center(:))./c.state_scale(:))));
    action=getAction(actor,{observation});a=double(action{1}(:)');
    lower=levels(1);upper=levels(end);
    if isfield(c,'action_lower_limit'),lower=c.action_lower_limit(1);upper=c.action_upper_limit(1);end
    assert(a(1)>=lower && a(1)<=upper && a(2)==0);
    [~,index]=min(abs(a(1)-levels));
    vector=struct(boot_id=string(t.boot_id),telemetry_seq=t.seq,source_t_us=t.t_us, ...
        history=h,observation=double(observation)',raw_action=a,projected_absolute_action=[levels(index) 0], ...
        projected_kp=double(single(.003389+levels(index)*.00027112)),projected_ki=double(single(.00144)), ...
        nearest_threshold_distance=min(abs(a(1)-thresholds)),hardware_writeback=false);
    vectors{end+1}=vector; %#ok<AGROW>
end
assert(numel(vectors)>100);
exportMotorTD3DiagnosticJSON(checkpoint,fullfile(output,'networks.json'));
report=struct(schema_version=1,checkpoint_sha256=motorFileSHA256(checkpoint), ...
    actual_telemetry_sha256=motorFileSHA256(fullfile(trial,'telemetry.jsonl')), ...
    policy_definition="Frozen MATLAB Actor + nearest listed experimental absolute-action level; Ki fixed", ...
    experimental_projection_levels=levels,ordinary_gain_domain_qualification_granted=false, ...
    projection_is_part_of_policy=true,projection_is_not_raw_actor_action=true, ...
    vectors=numel(vectors),hardware_accessed=false,hardware_writeback=false, ...
    actor_benchmark_performed=false,physical_performance_verified=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(output,'references.json'),[vectors{:}]);write(fullfile(output,'policy-reference-summary.json'),report);
disp(jsonencode(report));
end

function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
