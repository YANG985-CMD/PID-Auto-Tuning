function ccmp_plot(traces,labels,output)
f=figure('Color','w','Position',[100 80 1250 850]); tiledlayout(3,2,'TileSpacing','compact');
colors=lines(5);
nexttile; plot(traces{1}.time_s,traces{1}.reference_rpm,'k--','LineWidth',1.5); hold on;
for k=1:5, plot(traces{k}.time_s,traces{k}.speed_rpm,'Color',colors(k,:)); end
title('Reference PMSM: same scenario'); ylabel('Speed (rpm)'); legend(['Reference',labels],'Location','best'); grid on;
nexttile; hold on; for k=1:5, plot(traces{k}.time_s,traces{k}.reference_rpm-traces{k}.speed_rpm,'Color',colors(k,:)); end
title('Tracking error'); ylabel('Error (rpm)'); grid on;
nexttile; hold on; for k=1:5, plot(traces{k}.time_s,max(abs(traces{k}{:,{'ia_A','ib_A','ic_A'}}),[],2),'Color',colors(k,:)); end
title('Peak absolute phase current'); ylabel('Current (A)'); grid on;
nexttile; plot(traces{1}.time_s,traces{1}.load_Nm,'k'); title('Shared load disturbance'); ylabel('Load (Nm)'); grid on;
nexttile; hold on; for k=1:5, stairs(traces{k}.time_s,traces{k}.Kp,'Color',colors(k,:)); end
title('Applied Kp after common guard'); xlabel('Time (s)'); grid on;
nexttile; hold on; for k=1:5, stairs(traces{k}.time_s,traces{k}.Ki,'Color',colors(k,:)); end
title('Applied Ki after common guard'); xlabel('Time (s)'); grid on;
exportgraphics(f,fullfile(output,'comparison_curves.png'),'Resolution',170);
savefig(f,fullfile(output,'comparison_curves.fig'));
end
