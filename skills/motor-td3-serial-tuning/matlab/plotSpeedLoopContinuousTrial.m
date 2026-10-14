function plotSpeedLoopContinuousTrial(trial,output,profile)
% Actual motor telemetry only; no counterfactual or synthetic response curve.
arguments
    trial (1,1) string
    output (1,1) string
    profile (1,1) string {mustBeMember(profile,["td3","ki-response"])} = "td3"
end
rows=cellfun(@jsondecode,cellstr(splitlines(strtrim(fileread(fullfile(trial,'telemetry.jsonl'))))),UniformOutput=false);
s=jsondecode(fileread(fullfile(trial,'summary.json')));assert(s.passed);
t=[rows{:}];t=t([t.enabled]);x=([t.t_us]-s.trial_timing.started_us)/1e6;
f=figure('Visible','off','Color','white','Position',[100 100 1100 720]);cleanup=onCleanup(@()close(f));
layout=tiledlayout(f,3,1,'Padding','compact','TileSpacing','compact');
heading='实机连续采集与异步 TD3 训练：单次启动，Actor 尚未下发';
if profile=="ki-response",heading='实机 Ki 响应采集：固定 Kp，未训练或下发 Ki Actor';end
title(layout,heading,'FontName','Microsoft YaHei');
a=nexttile(layout);plot(a,x,[t.speed_ref],'--','LineWidth',1.4);hold(a,'on');plot(a,x,[t.speed],'LineWidth',.8);
ylabel(a,'Hall 转速 / rpm');legend(a,{'实际目标转速','实测 Hall 转速'},'Location','best');grid(a,'on');
b=nexttile(layout);
if profile=="ki-response",plot(b,x,[t.ki]*1000,'LineWidth',1);ylabel(b,'实际 Ki × 1000');
else,plot(b,x,[t.kp]*1000,'LineWidth',1);ylabel(b,'实际 Kp × 1000');end
grid(b,'on');
c=nexttile(layout);plot(c,x,[t.current],'LineWidth',.8);ylabel(c,'三相最大名义电流 / A');xlabel(c,'运行时间 / s');grid(c,'on');
for ax=[a b c]
    set(ax,'FontName','Microsoft YaHei');xlim(ax,[0 24]);
    xline(ax,(s.trial_timing.run_started_us-s.trial_timing.started_us)/1e6,':','进入闭环', ...
        'HandleVisibility','off','FontName','Microsoft YaHei');
    xline(ax,23.8,':','STOP','HandleVisibility','off');
end
exportgraphics(f,output,'Resolution',160);
end
