function report=auditMotorFrozenHallSectorPattern(input,replaySummary,outputFolder)
% A fixed training-only Hall-code association tested on independent boots.
% Residuals are a diagnostic decomposition, never a replacement motor score.
arguments
    input (1,1) string
    replaySummary (1,1) string
    outputFolder (1,1) string
end
assert(isfolder(outputFolder) && ~isfile(fullfile(outputFolder,'summary.json')));
s=load(input);assert(s.fullHallAudit.passed);
m=jsondecode(fileread(replaySummary));assert(m.passed);
rows=[s.fullHallTrain;s.fullHallValidation];keys=string(cellfun(@(r)char(r.physical_key),rows,UniformOutput=false));
assert(numel(unique(keys))==numel(keys) && numel(keys)==m.total_unique_windows);
assert(isempty(intersect(s.fullHallContract.training_boot_ids,s.fullHallContract.validation_boot_ids)));
hall=containers.Map('KeyType','char','ValueType','any');hallSHA=containers.Map('KeyType','char','ValueType','char');
for b=m.whole_boot_split(:)'
    path=fullfile(b.raw_folder,'full-hall-audit/full-hall-edges.json');h=jsondecode(fileread(path));
    assert(string(h.boot_id)==string(b.boot_id) && h.full_session_history);
    hall(b.boot_id)=h.records;hallSHA(b.boot_id)=char(motorFileSHA256(path));
end
parts=cell(numel(rows),1);seen=false(numel(rows),1);windowRows=struct([]);maxError=0;
for item=m.input_manifest(:)'
    assert(motorFileSHA256(item.file)==string(item.sha256));w=jsondecode(fileread(item.file));
    assert(motorFileSHA256(item.raw_window_file)==string(item.raw_window_sha256));
    assert(string(w.raw_window_sha256)==string(item.raw_window_sha256));
    index=find(keys==string(item.physical_key));assert(isscalar(index) && ~seen(index));seen(index)=true;r=rows{index};
    assert(string(w.physical_key)==string(r.physical_key) && string(w.boot_id)==string(r.boot_id));
    if any(string(r.boot_id)==s.fullHallContract.training_boot_ids),expected="train";else
        assert(any(string(r.boot_id)==s.fullHallContract.validation_boot_ids));expected="validation";
    end
    assert(string(item.split)==expected && string(w.split)==expected);
    assert(w.state.kp==r.actual_source_kp && w.action_applied(1)==r.actual_target_kp && w.state.speed_ref==1000);
    h=w.full_hall_reward;assert(string(h.full_hall_sha256)==string(hallSHA(w.boot_id)));
    trace=h.records(:);original=hall(w.boot_id);assert(isequal(original([trace.edge]),trace));
    assert(all([trace.valid]) && all([trace.model_stage]==4));
    assert(all(diff([trace.edge])==1) && all(diff([trace.t_us])==[trace(2:end).period_us]));
    lo=max(h.begin_us,[trace(1:end-1).t_us]');hi=min(h.end_us,[trace(2:end).t_us]');
    width=max(0,hi-lo);mask=width>0;error=1000-[trace(1:end-1).rpm]';code=[trace(1:end-1).hall_code]';
    assert(sum(width)==r.measured_reward_span_us && all(ismember(code(mask),1:6)));
    mse=sum(width.*error.^2)/sum(width);maxError=max(maxError,abs(mse-h.mse_rpm2));
    assert(maxError<1e-7);
    n=nnz(mask);
    parts{index}=table(repmat(string(r.boot_id),n,1),repmat(expected,n,1), ...
        repmat(string(r.physical_key),n,1),repmat(w.state.elapsed_ms,n,1), ...
        repmat(r.actual_source_kp,n,1),repmat(r.actual_target_kp,n,1), ...
        code(mask),width(mask),error(mask),lo(mask),hi(mask), ...
        VariableNames=["Boot","Split","PhysicalKey","Elapsed_ms","SourceKp","TargetKp", ...
        "HallCode","Width_us","Error_rpm","Begin_us","End_us"]);
    v=struct(boot_id=string(r.boot_id),physical_key=string(r.physical_key),begin_us=h.begin_us,end_us=h.end_us);
    if isempty(windowRows),windowRows=v;else,windowRows(end+1)=v;end %#ok<AGROW>
end
assert(all(seen));T=vertcat(parts{:});
W=sortrows(struct2table(windowRows),["boot_id","begin_us"]);
same=W.boot_id(1:end-1)==W.boot_id(2:end);
assert(all(W.end_us(find(same))<=W.begin_us(find(same)+1))); %#ok<FNDSB>
late=T(T.Elapsed_ms>=10000,:);
baseline=abs(late.SourceKp/.003389-1)<1e-6 & late.SourceKp==late.TargetKp;
training=late(late.Split=="train" & baseline,:);
assert(numel(unique(training.Boot))==numel(s.fullHallContract.training_boot_ids));
model=fitMotorFrozenHallSectorPattern(training);
assert(isempty(intersect(model.fitting_boots,s.fullHallContract.validation_boot_ids)));
[matched,indices]=ismember(late.HallCode,model.codes);assert(all(matched));
late.FrozenDeviation_rpm=model.deviation_rpm(indices);
late.Residual_rpm=late.Error_rpm-late.FrozenDeviation_rpm;
validation=late(late.Split=="validation",:);
baseValid=validation(abs(validation.SourceKp/.003389-1)<1e-6 & validation.SourceKp==validation.TargetKp,:);
holdValid=validation(validation.SourceKp==validation.TargetKp,:);
switchValid=validation(validation.SourceKp~=validation.TargetKp,:);
groups=struct(all_late_validation=score(validation),baseline_late_validation=score(baseValid), ...
    held_gain_late_validation=score(holdValid),changed_gain_late_validation=score(switchValid));
v=validation;v.RawSquare=v.Width_us.*v.Error_rpm.^2;v.ResidualSquare=v.Width_us.*v.Residual_rpm.^2;
B=groupsummary(v,"Boot","sum",["Width_us","RawSquare","ResidualSquare"]);
B.RawRMSE=sqrt(B.sum_RawSquare./B.sum_Width_us);B.ResidualRMSE=sqrt(B.sum_ResidualSquare./B.sum_Width_us);
B.DescriptiveResidualMSEFraction=1-B.sum_ResidualSquare./B.sum_RawSquare;
report=struct(passed=true,input_sha256=motorFileSHA256(input),replay_sha256=motorFileSHA256(replaySummary), ...
    physical_unique_windows=numel(rows),new_physical_windows=0,unique_segments=height(T), ...
    primary_window_MSE_maximum_difference=maxError,source_hashes_and_nonoverlapping_windows_verified=true, ...
    fixed_late_source_elapsed_threshold_ms=10000,training_baseline_windows=numel(unique(training.PhysicalKey)), ...
    fixed_model=model,validation_groups=groups,validation_by_boot=table2struct(B), ...
    independent_speed_ground_truth=false,pattern_is_not_identified_sensor_noise=true, ...
    corrected_residual_is_not_an_acceptance_metric=true, ...
    interpretation="Hall-code association can include sensor geometry, physical torque ripple, speed ripple and timing effects", ...
    original_rewards_and_feedback_and_primary_metric_unchanged=true,hardware_accessed=false, ...
    TD3_gradient_updates=0,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
writetable(late,fullfile(outputFolder,'late-Hall-segments.csv'));
writetable(B,fullfile(outputFolder,'validation-by-boot.csv'));
save(fullfile(outputFolder,'diagnostic-data.mat'),'T','late','model','report');
write(fullfile(outputFolder,'summary.json'),report);
disp(jsonencode(struct(passed=true,groups=groups,model=model.deviation_rpm, ...
    windows=numel(rows),maximum_primary_MSE_error=maxError)));
end
function out=score(T)
assert(~isempty(T));weight=sum(T.Width_us);
raw=sum(T.Width_us.*T.Error_rpm.^2)/weight;residual=sum(T.Width_us.*T.Residual_rpm.^2)/weight;
out=struct(windows=numel(unique(T.PhysicalKey)),boots=numel(unique(T.Boot)),scored_duration_us=weight, ...
    unchanged_raw_Hall_RMSE_rpm=sqrt(raw),diagnostic_residual_RMSE_rpm=sqrt(residual), ...
    descriptive_MSE_reduction_percent=100*(1-residual/raw),physical_speed_improvement_proven=false);
end
function write(path,value)
assert(~isfile(path));f=fopen(path,'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
