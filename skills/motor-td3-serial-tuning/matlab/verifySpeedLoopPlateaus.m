function result=verifySpeedLoopPlateaus(rawFile,analysisFile,outputFile)
% Independently recompute measured plateau metrics with MATLAB trapz.
analysis=jsondecode(fileread(analysisFile));lines=splitlines(string(fileread(rawFile)));
lines=lines(strlength(lines)>0);packets=cell(numel(lines),1);
for i=1:numel(lines),packets{i}=jsondecode(lines(i));end
packets=vertcat(packets{:});seq=[packets.seq];allMse=zeros(numel(analysis.plateaus),1);
allCurrent=allMse;allSpeed=allMse;
for j=1:numel(analysis.plateaus)
    row=analysis.plateaus(j);mask=seq>=row.first_seq & seq<=row.last_seq;
    p=packets(mask);assert(numel(p)==row.packet_count && all(diff([p.seq])==1));
    assert(all([p.enabled]) && all([p.fault]==0) && all([p.kp]==row.kp) && all([p.ki]==row.ki));
    t=double([p.t_us]);err=double([p.speed_ref])-double([p.speed]);
    mse=trapz(t,err.^2)/(t(end)-t(1));current=max([p.current]);speed=max(abs([p.speed]));
    assert(abs(mse-row.mse_rpm2)<1e-9 && abs(sqrt(mse)-row.rmse_rpm)<1e-10);
    assert(current==row.peak_nominal_current_a && speed==row.peak_speed_rpm);
    assert(t(end)-t(1)==row.duration_us);
    allMse(j)=mse;allCurrent(j)=current;allSpeed(j)=speed;
end
levels=unique([analysis.plateaus.level]);metrics=struct([]);
for j=1:numel(levels)
    level=levels(j);mask=[analysis.plateaus.level]==level;
    record=struct('level',level,'rmse_rpm',sqrt(mean(allMse(mask))),...
        'mean_peak_nominal_current_a',mean(allCurrent(mask)),'mean_peak_speed_rpm',mean(allSpeed(mask)));
    % jsondecode prefixes numeric JSON keys with x.
    expected=analysis.metrics.(sprintf('x%d',level));
    assert(abs(record.rmse_rpm-expected.rmse_rpm)<1e-10);
    assert(abs(record.mean_peak_nominal_current_a-expected.mean_peak_nominal_current_a)<1e-12);
    assert(abs(record.mean_peak_speed_rpm-expected.mean_peak_speed_rpm)<1e-10);
    if isempty(metrics),metrics=record;else,metrics(end+1)=record;end %#ok<AGROW>
end
result=struct('passed',true,'verified_actual_plateaus',numel(analysis.plateaus),...
    'metrics',metrics,'independent_runtime','MATLAB trapz from raw telemetry',...
    'training_performed',false,'deployment_allowed',false,'performance_claim_allowed',false);
fid=fopen(outputFile,'w');assert(fid>=0);c=onCleanup(@()fclose(fid));
fprintf(fid,'%s\n',jsonencode(result,PrettyPrint=true));disp(jsonencode(result));
end
