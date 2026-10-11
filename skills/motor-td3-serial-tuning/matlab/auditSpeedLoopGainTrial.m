function report = auditSpeedLoopGainTrial(runDir, outputDir)
% Audit real command/feedback logs without starting hardware or training.
% Startup responses are excluded: the vendor Align/Open plan lasts 2.2 s.
arguments
    runDir (1,1) string
    outputDir (1,1) string
end
if ~isfolder(outputDir), mkdir(outputDir); end
rows = splitlines(strtrim(fileread(fullfile(runDir,"telemetry.jsonl"))));
assert(~isempty(rows) && strlength(rows(1))>0,"No complete telemetry");
data = cellfun(@jsondecode,cellstr(rows),UniformOutput=false);
data = vertcat(data{:});
% JSON null is kept missing; it is never replaced by a fabricated temperature.
T = table([data.seq]',[data.t_us]',[data.t_apply_us]',[data.applied_seq]', ...
    [data.enabled]',[data.fault]',[data.elapsed_ms]',[data.speed]', ...
    [data.current]',[data.kp]',[data.ki]',[data.vbus]', ...
    VariableNames=["seq","t_us","t_apply_us","applied_seq","enabled", ...
    "fault","elapsed_ms","speed","current","kp","ki","vbus"]);
commands = splitlines(strtrim(fileread(fullfile(runDir,"commands.jsonl"))));
commands = cellfun(@jsondecode,cellstr(commands),UniformOutput=false);
gainCommands = commands(cellfun(@(c)string(c.type)=="gains",commands));
matched = zeros(0,1); latencies = zeros(0,1);
for index = 1:numel(gainCommands)
    command = gainCommands{index};
    actual = T(T.applied_seq==command.command_seq & T.enabled,:);
    if isempty(actual), continue; end
    assert(all(actual.kp==command.kp & actual.ki==command.ki),"Gain mismatch");
    assert(all(actual.t_apply_us>=command.source_t_us & ...
        actual.t_apply_us<=command.expires_us),"Action timing mismatch");
    matched(end+1,1) = command.command_seq; %#ok<AGROW>
    latencies(end+1,1) = (actual.t_apply_us(1)-command.source_t_us)/1000; %#ok<AGROW>
end
assert(all(diff(T.seq)==1) && all(diff(T.t_us)>0),"Telemetry order failure");
active = T(T.enabled,:);
closed = active(active.elapsed_ms>=2200,:);
fault = jsondecode(fileread(fullfile(runDir,"fault-readback.json")));
run = jsondecode(fileread(fullfile(runDir,"summary.json")));
report = struct(schema_version=1,source="real_motor",firmware_id=string(run.firmware_id), ...
    hardware_accessed=true,matlab_release=string(version("-release")), ...
    complete_telemetry_packets=height(T),active_snapshots=height(active), ...
    commanded_gain_actions=numel(gainCommands),actual_gain_actions=numel(matched), ...
    actual_gain_sequences=matched',gain_pairs=unique(active{:, ["kp","ki"]},"rows"), ...
    median_sample_interval_ms=median(diff(T.t_us))/1000, ...
    actual_apply_latency_ms_range=[min(latencies),max(latencies)], ...
    observed_active_ms_range=[min(active.elapsed_ms),max(active.elapsed_ms)], ...
    nominal_peak_current_a=max(active.current),sampled_peak_speed_rpm=max(abs(active.speed)), ...
    guard_fault_after_stop=fault.guard_fault,post_stop_hall_speed_rpm=fault.HallSpeed, ...
    chart_motor_state_after_stop=fault.chart_motor_state, ...
    closed_loop_snapshots=height(closed),eligible_td3_experiences=0, ...
    td3_training_performed=false,actor_deployed=false, ...
    exclusion_reason="Trial tripped during vendor open-loop startup; no closed-loop PI response", ...
    temperature_c=NaN,current_conversion_independently_calibrated=false);
% Do not call the startup tracking error a closed-loop controller score.
report.closed_loop_rmse_rpm = NaN;
writetable(T,fullfile(outputDir,"telemetry.csv"));
fid=fopen(fullfile(outputDir,"analysis.json"),"w","n","UTF-8");
assert(fid>=0,"Cannot write analysis");
closer=onCleanup(@() fclose(fid));
fprintf(fid,"%s\n",jsonencode(report,PrettyPrint=true));
clear closer
fig=figure(Name="Real motor gain application audit",Color="w",Visible="off");
layout=tiledlayout(fig,3,1,TileSpacing="compact");
nexttile(layout);plot(active.elapsed_ms/1000,active.speed,"LineWidth",1.2);
yline(1000,"--");yline(1800,":");ylabel("Hall speed (rpm)");grid on;
title("Real startup capture; guard fault 5 before closed loop");
nexttile(layout);plot(active.elapsed_ms/1000,active.applied_seq,"LineWidth",1.2);
ylabel("Actual gain sequence");grid on;
nexttile(layout);plot(active.elapsed_ms/1000,active.current,"LineWidth",1.2);
ylabel("Nominal phase current (A)");xlabel("Time since BEGIN (s)");grid on;
exportgraphics(fig,fullfile(outputDir,"gain-trial-audit.png"),Resolution=180);
close(fig);
end
