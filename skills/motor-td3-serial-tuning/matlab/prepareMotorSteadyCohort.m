function report=prepareMotorSteadyCohort(input,eligibilityPath,output,options)
% Exact predeclared plateau membership, preserving rewards and whole-boot split.
arguments
    input (1,1) string
    eligibilityPath (1,1) string
    output (1,1) string
    options.CausalView (1,1) string=""
end
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
eligibility=jsondecode(fileread(eligibilityPath));assert(eligibility.passed);
assert(eligibility.selection_uses_predeclared_actual_plateau_analysis_spans);
causal=s.fullHallContract.observation_profile=="causal-six-period-Hall-sector-v1";
if causal
    assert(motorFileSHA256(options.CausalView)==string(s.fullHallContract.observation_view_sha256));
    view=jsondecode(fileread(options.CausalView));
else
    assert(s.fullHallContract.observation_profile=="history20-40");
end
original=[s.fullHallTrain;s.fullHallValidation];allKeys=string(cellfun(@(r)r.physical_key,original,UniformOutput=false));
assert(numel(allKeys)==eligibility.unique_original_windows);
expectedKeys=string({eligibility.eligibility.physical_key});
assert(isequal(sort(allKeys),sort(expectedKeys(:))));
trainRaw=[];selectedRows=cell(0,1);selectedFeatures=cell(0,1);selectedNext=cell(0,1);selectedSplit=strings(0,1);
analysisSources=containers.Map('KeyType','char','ValueType','any');
for row=eligibility.eligibility(:)'
    assert(motorFileSHA256(row.original_replay_window)==string(row.original_replay_window_sha256));
    w=jsondecode(fileread(row.original_replay_window));assert(string(w.physical_key)==string(row.physical_key));
    if ~isKey(analysisSources,row.source_plateau_analysis)
        assert(motorFileSHA256(row.source_plateau_analysis)==string(row.source_plateau_analysis_sha256));
        analysisSources(row.source_plateau_analysis)=jsondecode(fileread(row.source_plateau_analysis));
    end
    a=analysisSources(row.source_plateau_analysis);assert(a.passed && string(a.boot_id)==string(row.boot_id));
    p=w.state_history(1);elapsed=p.elapsed_ms*1000;margin=max(2,abs(elapsed)*2^-22+1);
    lo=row.clock_origin_us+elapsed-margin;
    p=w.response(end);elapsed=p.elapsed_ms*1000;margin=max(2,abs(elapsed)*2^-22+1);
    hi=row.clock_origin_us+elapsed+margin;
    assert(abs(row.snapshot_lower_us-lo)<1e-7 && abs(row.snapshot_upper_us-hi)<1e-7);
    matches=[a.plateaus.kp]==w.state.kp & [a.plateaus.kp]==w.action_applied(1) & ...
        row.clock_origin_us+1000*[a.plateaus.analysis_start_ms]<=lo & ...
        row.clock_origin_us+1000*[a.plateaus.analysis_end_ms]>=hi;
    assert(sum(matches)<=1 && row.selected_for_matched_steady_cohort==any(matches));
    if ~any(matches),continue;end
    assert(a.plateaus(matches).slot==row.selected_plateau_slot);
    index=find(allKeys==string(row.physical_key));assert(isscalar(index));
    old=original{index};assert(string(old.boot_id)==string(row.boot_id));
    if causal
        featureRow=view.rows(string({view.rows.physical_key})==string(row.physical_key));assert(isscalar(featureRow));
        x=featureRow.features(:)';nx=featureRow.next_features(:)';
    else
        x=rawFeatures(w.state_history);nx=rawFeatures(w.response(end-2:end));
    end
    selectedRows{end+1,1}=old;selectedFeatures{end+1,1}=x;selectedNext{end+1,1}=nx; %#ok<AGROW>
    selectedSplit(end+1,1)=string(row.split); %#ok<AGROW>
    if string(row.split)=="train",trainRaw=[trainRaw;x;nx];end %#ok<AGROW>
end
fullHallContract=s.fullHallContract;fullHallContract.state_center=mean(trainRaw,1);
if causal,floorScale=[.1 .1 .02 .02 .1 .1 .1 .05 .1 .1];else,floorScale=[.1 .1 .02 .02 .1 .1 .1 .05 .02 1];end
fullHallContract.state_scale=max(std(trainRaw,0,1),floorScale);
if ~causal,fullHallContract.state_center(10)=0;fullHallContract.state_scale(10)=1;end
fullHallContract.training_cohort="predeclared-steady-plateau-source-and-response-v1";
fullHallContract.cohort_selection_sha256=motorFileSHA256(eligibilityPath);
fullHallContract.normalization_source="Selected training boots only, source and next states";
fullHallTrain={};fullHallValidation={};
for index=1:numel(selectedRows)
    old=selectedRows{index};next=old;
    next.observation=single(max(-5,min(5,(selectedFeatures{index}-fullHallContract.state_center)./fullHallContract.state_scale)))';
    next.next_observation=single(max(-5,min(5,(selectedNext{index}-fullHallContract.state_center)./fullHallContract.state_scale)))';
    assert(isequaln(rmfield(old,{'observation','next_observation'}),rmfield(next,{'observation','next_observation'})));
    if selectedSplit(index)=="train",fullHallTrain{end+1,1}=next;else,fullHallValidation{end+1,1}=next;end %#ok<AGROW>
end
assert(numel(fullHallTrain)==eligibility.selected_counts.train && numel(fullHallValidation)==eligibility.selected_counts.validation);
assert(numel(fullHallTrain)>=128 && numel(fullHallValidation)>=128);
fullHallAudit=s.fullHallAudit;fullHallAudit.unique_train_windows=numel(fullHallTrain);
fullHallAudit.unique_validation_windows=numel(fullHallValidation);
fullHallAudit.retained_from_original_reward_checks=numel(allKeys);
fullHallAudit.independent_full_hall_reward_checks=numel(selectedRows);
report=struct(passed=true,original_windows=numel(allKeys),selected_windows=numel(selectedRows), ...
    training_windows=numel(fullHallTrain),validation_windows=numel(fullHallValidation), ...
    source_input_sha256=motorFileSHA256(input),cohort_selection_sha256=motorFileSHA256(eligibilityPath), ...
    observation_profile=fullHallContract.observation_profile,matched_steady_spans=true, ...
    all_original_experiences_retained=true,physical_rewards_unchanged=true,actual_actions_unchanged=true, ...
    whole_boot_split_unchanged=true,training_only_normalization=true,hardware_accessed=false, ...
    training_performed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
save(output,'fullHallAudit','fullHallContract','fullHallTrain','fullHallValidation','report');disp(jsonencode(report));
end

function x=rawFeatures(h)
t=h(end);x=[t.speed_ref t.speed t.speed_ref-t.speed h(end-1).speed_ref-h(end-1).speed ...
    t.integral_output t.current t.vbus t.kp h(end-2).speed_ref-h(end-2).speed t.elapsed_ms];
x=double(single(max(-5,min(5,x./[1000 1000 1000 1000 3 2 24 .003389 1000 3000]))));
end
