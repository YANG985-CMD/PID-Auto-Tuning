function report = tuneSkillPlan(output)
% Codex-managed offline search, followed by an explicit frozen plan replay.
% Search uses a separate 2.5s scenario; no chat agent is simulated in Simulink.
root=fileparts(mfilename('fullpath')); addpath(root); ccmp_init(); c=ccmp_config();
if nargin==0, output=root; end
[speed,load]=ccmp_scenario('tuning'); candidates=struct([]); n=0;
cleanup=onCleanup(@()evalin('base','clear ccmpPlanOverride'));
for pk=[.92 1 1.08]
    for ik=[.9 1 1.1]
        n=n+1; gains=c.baseline.*[pk;ik];
        assignin('base','ccmpPlanOverride',[0 gains']); clear ccmp_assets
        in=Simulink.SimulationInput('MotorTunerComparison');
        in=in.setVariable('ccmpSpeedRef',speed).setVariable('ccmpLoad',load).setVariable('ccmpMethod',1);
        in=in.setModelParameter('StopTime','2.5'); out=sim(in);
        metric=ccmp_metrics(ccmp_trace(out));
        candidate=struct('Kp',gains(1),'Ki',gains(2),'rmse_rpm',metric.rmse_rpm, ...
            'peak_phase_current_A',metric.peak_phase_current_A,'saturation_fraction',metric.iq_command_saturation_fraction);
        if isempty(candidates), candidates=candidate; else, candidates(end+1)=candidate; end %#ok<AGROW>
    end
end
[~,best]=min([candidates.rmse_rpm]); chosen=candidates(best);
plan=table(0,chosen.Kp,chosen.Ki,'VariableNames',{'time_s','Kp','Ki'});
writetable(plan,fullfile(output,'ai_approved_plan.csv'));
writetable(struct2table(candidates),fullfile(output,'ai_plan_search.csv'));
report=struct('source','Codex-managed deterministic offline Simulink parameter search', ...
    'online_chat_decisions_simulated',false,'search_scenario','Independent 2.5s tuning scenario', ...
    'comparison_scenario_used_for_search',false,'objective','Full tuning-scenario speed RMSE', ...
    'candidate_count',n,'selected',chosen,'approved_for','Simulation plan replay only', ...
    'hardware_accessed',false,'deployment_allowed',false,'performance_claim_allowed',false);
fid=fopen(fullfile(output,'ai_plan_report.json'),'w'); fwrite(fid,jsonencode(report,PrettyPrint=true)); fclose(fid);
clear cleanup; clear ccmp_assets; disp(report);
end
