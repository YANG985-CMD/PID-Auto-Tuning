function report = auditSpeedLoopClosedLoopTrial(runDir, outputDir)
% Audit motion-v4 real data. No hardware commands, replay insertion or training.
% Elapsed time predicts a stage; only the retained Hall ring proves its stage.
arguments
    runDir (1,1) string
    outputDir (1,1) string
end
if ~isfolder(outputDir), mkdir(outputDir); end
run = jsondecode(fileread(fullfile(runDir,"summary.json")));
assert(run.passed && string(run.firmware_id)=="g431-speedloop-pi-motion-v4");
data = readJSONLines(fullfile(runDir,"telemetry.jsonl"));
commands = readJSONLines(fullfile(runDir,"commands.jsonl"));
ring = jsondecode(fileread(fullfile(runDir,"hall-edges.json")));
data = vertcat(data{:});
names = ["seq","t_us","t_apply_us","applied_seq","enabled","fault", ...
    "elapsed_ms","speed_ref","speed","error_history","integral_output", ...
    "current","kp","ki","vbus"];
T = table;
for name = names, T.(name) = [data.(name)]'; end
assert(all(isfinite(T{:,:}),"all") && all(diff(T.seq)==1) && all(diff(T.t_us)>0));
assert(all(T.fault==0) && all(arrayfun(@(r)isempty(r.temperature_c),data)));
active = T(T.enabled==1,:);
assert(all(abs(active.speed)<1800) && all(active.current<2) && ...
    all(active.vbus>=18 & active.vbus<=30));
stopped = T(T.seq>active.seq(end) & T.enabled==0,:);
assert(~isempty(stopped) && run.protocol_stop_acknowledged && ...
    run.core_halted_after_physical_shutdown && run.can_released_after_shutdown);
final = run.final_board_state;
assert(bitand(uint32(final.tim1_bdtr),uint32(hex2dec('8000')))==0 && ...
    bitand(uint32(final.tim1_ccer),uint32(hex2dec('555')))==0 && ...
    bitand(uint32(final.gpioa_moder),uint32(hex2dec('3f0000')))==hex2dec('150000') && ...
    bitand(uint32(final.gpiob_moder),uint32(hex2dec('fc000000')))==hex2dec('54000000') && ...
    bitand(uint32(final.gpioa_odr),uint32(hex2dec('700')))==0 && ...
    bitand(uint32(final.gpiob_odr),uint32(hex2dec('e000')))==0);

gains = commands(cellfun(@(c)string(c.type)=="gains",commands));
latencies = zeros(numel(gains),1);
for i = 1:numel(gains)
    c = gains{i}; actual = active(active.applied_seq==c.command_seq,:);
    assert(~isempty(actual) && all(actual.kp==c.kp & actual.ki==c.ki),"Missing actual gain acknowledgement");
    assert(all(actual.t_apply_us>=c.source_t_us & actual.t_apply_us<=c.expires_us));
    latencies(i) = (actual.t_apply_us(1)-c.source_t_us)/1000;
end
assert(all(diff(active.applied_seq)>=0));
edges = ring.records;
assert(~isempty(edges) && all([edges.valid]) && all(diff([edges.t_us])>0));
% Check raw periods and the vendor forward Hall sector order independently.
order = [5 4 6 2 3 1];
for i = 1:numel(edges)
    e = edges(i); previous = find(order==e.previous_code,1);
    assert(~isempty(previous) && order(mod(previous,6)+1)==e.hall_code);
    assert(e.period_us>0 && abs(e.rpm-5000000/e.period_us)<.001);
    if i>1, assert(e.period_us==e.t_us-edges(i-1).t_us); end
end
assert(all([edges.model_stage]==4),"Retained edge window does not prove continuous RunStage");
proofStart = edges(1).t_us; proofEnd = edges(end).t_us;
proven = active(active.t_us>=proofStart & active.t_us<=proofEnd,:);
planned = active(active.elapsed_ms>=2200,:);
assert(~isempty(proven));

% Export individual causal candidates; this is NOT a training admission gate.
% Source state is the exact packet used by the writer. Stop/fault frames never
% become a next_state. The next command's source cuts the preceding window,
% so two actions cannot claim overlapping response samples.
scales = [1000 1000 1000 1000 3 2 24 .003389 .00144 3000];
stateNames = ["speed_ref","speed","speed_error","error_history", ...
    "integral_output","current","vbus","kp","ki","elapsed_ms"];
candidates = cell(0,1);
for i = 1:numel(gains)
    c = gains{i}; source = active(active.t_us==c.source_t_us,:);
    if isempty(source) || source.elapsed_ms<2200, continue; end
    response = active(active.applied_seq==c.command_seq & active.t_us>active.t_apply_us,:);
    if i<numel(gains), response = response(response.t_us<=gains{i+1}.source_t_us,:); end
    if isempty(response), continue; end
    endpoint = response(end,:); ta = endpoint.t_apply_us;
    assert(source.t_us<=ta && ta<endpoint.t_us);
    assert(all(response.kp==c.kp & response.ki==c.ki));
    s = makeState(source); ns = makeState(endpoint);
    action = [(c.kp-source.kp)/.00027112, (c.ki-source.ki)/.000144];
    assert(all(abs(action)<=1+1e-6));
    % Pending-command packets still count for link continuity. Using only
    % acknowledged packets would confuse application latency with frame loss.
    interval = active(active.t_us>=source.t_us & active.t_us<=endpoint.t_us,:);
    gaps = diff(interval.t_us)/1000;
    assert(all(gaps>0) && max(gaps)<=40);
    errMse = mean(((response.speed_ref-response.speed)/1000).^2);
    currentMse = mean((response.current/2).^2);
    peak = max(abs(response.current))/2;
    overshoot = max(0,max(response.speed-response.speed_ref))/1000;
    saturation = mean(abs(response.current)>=1.98);
    reward = -errMse-.05*currentMse-.012*peak^2-.025*max(0,peak-.7)^2 ...
        -.04*saturation-.02*overshoot^2-.001*sum(action.^2);
    confirmed = source.t_us>=proofStart && endpoint.t_us<=proofEnd;
    candidate = struct(schema_version=1,source="real_motor", ...
        firmware_id=string(run.firmware_id),command_seq=c.command_seq, ...
        t_state_us=source.t_us,t_apply_us=ta,t_next_us=endpoint.t_us, ...
        telemetry_seq_start=source.seq,telemetry_seq_end=endpoint.seq, ...
        state=s,next_state=ns,observation=max(-5,min(5,s./scales)), ...
        next_observation=max(-5,min(5,ns./scales)),action_normalized=action, ...
        action_applied=[c.kp c.ki],reward=reward, ...
        stage_confirmed_from_raw_edges=confirmed, ...
        model_stage_basis="elapsed-plan-only",response_ms=(endpoint.t_us-ta)/1000, ...
        max_frame_gap_ms=max(gaps),terminated=false,truncated=false, ...
        learner_eligible=false,exclusion_reason="Audit candidates only; ordinary live-training gates not admitted");
    if confirmed, candidate.model_stage_basis="retained-continuous-RunStage-Hall-edges"; end
    candidates{end+1,1} = candidate; %#ok<AGROW>
end
% Do not fabricate an episode-end transition for this partial audit dataset.
writeJSONLines(fullfile(outputDir,"experience-candidates.jsonl"),candidates);
candidateCount = numel(candidates);
provenCount = sum(cellfun(@(c)c.stage_confirmed_from_raw_edges,candidates));
probe = planned(planned.kp>.0034,:);
returned = proven(proven.kp<.0034,:);
report = struct(schema_version=1,passed=true,source="real_motor",simulation_only=false, ...
    hardware_accessed=true,analysis_hardware_accessed=false,firmware_id=string(run.firmware_id), ...
    bin_sha256=string(run.bin_sha256),matlab_release=string(version("-release")), ...
    complete_telemetry_packets=height(T),active_snapshots=height(active), ...
    actual_gain_actions=numel(gains),gain_pairs=unique(active{:, ["kp","ki"]},"rows"), ...
    actual_apply_latency_ms_range=[min(latencies),max(latencies)], ...
    sample_interval_ms_range=[min(diff(T.t_us)),max(diff(T.t_us))]/1000, ...
    sampled_peak_speed_rpm=max(abs(active.speed)),nominal_peak_current_a=max(active.current), ...
    all_telemetry_faults_zero=true,stop_and_physical_shutdown_verified=true, ...
    retained_hall_edges=numel(edges),total_hall_edges=ring.total_edges, ...
    retained_hall_stage=4,raw_hall_rpm_range=[min([edges.rpm]),max([edges.rpm])], ...
    raw_stage_proof_t_us=[proofStart,proofEnd],raw_stage_confirmed_snapshots=height(proven), ...
    raw_stage_window_rmse_rpm=sqrt(mean((proven.speed-proven.speed_ref).^2)), ...
    expected_post_start_snapshots=height(planned), ...
    expected_post_start_window_rmse_rpm=sqrt(mean((planned.speed-planned.speed_ref).^2)), ...
    post_start_is_steady_state_score=false,probe_snapshots=height(probe), ...
    returned_gain_snapshots_in_proven_window=height(returned), ...
    causal_experience_candidates=candidateCount,raw_stage_confirmed_candidates=provenCount, ...
    eligible_td3_experiences=0,replay_warmup_required=128, ...
    td3_training_performed=false,actor_deployed=false, ...
    state_fields=stateNames,state_scale=scales,temperature_c=NaN, ...
    current_conversion_independently_calibrated=false, ...
    interpretation="One startup/probe/return trace proves application, not candidate improvement or four-method comparison", ...
    training_hold_reason="Too few independent closed-loop action windows; stage evidence retained only at end; normal live safety admission remains unchanged");
writetable(T,fullfile(outputDir,"telemetry.csv"));
writeJSON(fullfile(outputDir,"analysis.json"),report);
fig = figure(Name="SpeedLoop v4 real motor audit",Color="w",Visible="off");
layout = tiledlayout(fig,4,1,TileSpacing="compact");
nexttile(layout); plot(active.elapsed_ms/1000,active.speed,LineWidth=1.2);
yline(1000,"--");yline(1800,":");xline(2.2,":");ylabel("Hall rpm");grid on;
title("Real motor: 1000 rpm target; startup + 4% Kp probe + return");
nexttile(layout);stairs(active.elapsed_ms/1000,active.kp/.003389,LineWidth=1.2);
ylabel("Kp / baseline");grid on;
nexttile(layout);plot(active.elapsed_ms/1000,active.current,LineWidth=1.2);
ylabel("Nominal current (A)");grid on;
nexttile(layout);plot(([edges.t_us]-active.t_us(1))/1e6+active.elapsed_ms(1)/1000, ...
    [edges.rpm],"o-",LineWidth=1.1);yline(1000,"--");ylabel("Raw Hall rpm");
xlabel("Time since BEGIN (s)");grid on;title("Retained raw Hall edges: all model stage 4 (RunStage)");
exportgraphics(fig,fullfile(outputDir,"closed-loop-audit.png"),Resolution=180);
close(fig);
end

function values = readJSONLines(path)
lines = splitlines(strtrim(fileread(path)));
assert(~isempty(lines) && strlength(lines(1))>0);
values = cellfun(@jsondecode,cellstr(lines),UniformOutput=false);
end

function s = makeState(t)
s = [t.speed_ref,t.speed,t.speed_ref-t.speed,t.error_history,t.integral_output, ...
    t.current,t.vbus,t.kp,t.ki,t.elapsed_ms];
end

function writeJSON(path,value)
fid=fopen(path,"w","n","UTF-8");assert(fid>=0);
closer=onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid,"%s\n",jsonencode(value,PrettyPrint=true));
end

function writeJSONLines(path,values)
fid=fopen(path,"w","n","UTF-8");assert(fid>=0);
closer=onCleanup(@() fclose(fid)); %#ok<NASGU>
for i=1:numel(values), fprintf(fid,"%s\n",jsonencode(values{i})); end
end
