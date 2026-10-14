function summary = runComparison(output)
% Five deterministic runs through ONE shared referenced motor and FOC model.
root=fileparts(mfilename('fullpath')); addpath(root); ccmp_init(); c=ccmp_config();
if nargin==0, output=fullfile(root,'results'); end
if ~isfolder(output), mkdir(output); end
[speed,load]=ccmp_scenario('comparison'); rows=struct([]); traces=cell(5,1);
for method=1:5
    clear ccmp_assets
    in=Simulink.SimulationInput('MotorTunerComparison');
    in=in.setVariable('ccmpSpeedRef',speed).setVariable('ccmpLoad',load).setVariable('ccmpMethod',method);
    in=in.setModelParameter('StopTime',string(c.stopTime));
    started=tic; out=sim(in); wall=toc(started);
    disp(who(out));
    trace=ccmp_trace(out); traces{method}=trace;
    metric=ccmp_metrics(trace);
    metric.method=char(c.labels(method)); metric.method_id=method;
    metric.wall_clock_simulation_seconds=wall;
    metric.hardware_latency_measured=false; metric.hardware_accessed=false;
    metric.deployment_allowed=false; metric.performance_claim_allowed=false;
    if isempty(rows), rows=metric; else, rows(end+1)=metric; end %#ok<AGROW>
    writetable(trace,fullfile(output,sprintf('method_%d_trace.csv',method)));
    fprintf('%s: RMSE %.4f rpm, peak phase current %.4f A\n',c.labels(method),metric.rmse_rpm,metric.peak_phase_current_A);
end
summary=struct('source','Reference-model Simulink simulation', ...
    'plant_source',c.reference,'mechanical_parameters_identified_on_hardware',false, ...
    'stop_time_s',c.stopTime,'foc_period_s',c.focTs,'speed_PI_period_s',c.speedTs, ...
    'tuner_period_s',c.tunerTs,'guard_lower',c.lower','guard_upper',c.upper', ...
    'per_update_step',c.step','Kd',0,'metrics',rows, ...
    'hardware_accessed',false,'deployment_allowed',false,'performance_claim_allowed',false);
writetable(struct2table(rows),fullfile(output,'comparison_metrics.csv'));
save(fullfile(output,'comparison_data.mat'),'traces','summary');
fid=fopen(fullfile(output,'comparison_summary.json'),'w'); fwrite(fid,jsonencode(summary,PrettyPrint=true)); fclose(fid);
ccmp_plot(traces,c.labels,output);
disp(struct2table(rows));
end
