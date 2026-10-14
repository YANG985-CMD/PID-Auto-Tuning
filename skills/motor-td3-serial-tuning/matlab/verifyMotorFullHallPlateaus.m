function report=verifyMotorFullHallPlateaus(folder,output)
% Independently recompute the declared full-Hall metric from the raw edge trace.
arguments
    folder (1,1) string
    output (1,1) string
end
score=jsondecode(fileread(fullfile(folder,'full-hall-score.json')));
full=jsondecode(fileread(fullfile(folder,'full-hall-audit/full-hall-edges.json')));
lines=splitlines(string(fileread(fullfile(folder,'trial/telemetry.jsonl'))));lines=lines(strlength(lines)>0);
packets=cell(numel(lines),1);for i=1:numel(lines),packets{i}=jsondecode(lines(i));end
packets=vertcat(packets{:});first=find([packets.enabled],1);
assert(packets(first).applied_seq==0);origin=packets(first).t_apply_us;
assert(score.passed && full.full_session_history && string(score.boot_id)==string(full.boot_id));
edges=full.records([full.records.model_stage]==4);t=double([edges.t_us]);rpm=double([edges.rpm]);
assert(all(diff(t)==[edges(2:end).period_us]) && all([edges.valid]));
error2=(rpm(1:end-1)-1000).^2;rows=struct([]);
for row=score.plateaus(:)'
    assert(row.full_Hall_covered);lo=origin+row.score_span_ms(1)*1000;hi=origin+row.score_span_ms(2)*1000;
    widths=max(0,min(hi,t(2:end))-max(lo,t(1:end-1)));duration=sum(widths);
    assert(abs(duration-(hi-lo))<.01);
    mse=sum(widths.*error2)/duration;peak=max(abs(rpm(find(widths>0)))); %#ok<FNDSB>
    assert(abs(sqrt(mse)-row.full_Hall_hold_diagnostic_rmse_rpm)<1e-9);
    assert(peak==row.full_Hall_peak_speed_rpm);
    value=struct(slot=row.slot,rmse_rpm=sqrt(mse),peak_speed_rpm=peak,duration_us=duration);
    if isempty(rows),rows=value;else,rows(end+1)=value;end %#ok<AGROW>
end
report=struct(passed=true,boot_id=string(full.boot_id),plateaus_verified=numel(rows),rows=rows, ...
    source="MATLAB recomputation from complete raw Hall intervals",independent_speed_ground_truth=false, ...
    hardware_accessed=false,training_performed=false,actor_applied=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(rmfield(report,'rows')));
end
