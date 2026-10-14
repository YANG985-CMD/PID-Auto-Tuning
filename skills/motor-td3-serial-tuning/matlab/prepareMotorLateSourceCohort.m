function report=prepareMotorLateSourceCohort(input,replaySummary,output)
% One fixed >=10 s cohort; preserve actual transitions and parent coordinates.
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
rows=[s.fullHallTrain;s.fullHallValidation];
[~,proof,elapsed]=motorFactualResponseComponents(rows,s.fullHallContract,replaySummary);
n=numel(s.fullHallTrain);trainMask=elapsed(1:n)>=10000;validMask=elapsed(n+1:end)>=10000;
fullHallTrain=s.fullHallTrain(trainMask);fullHallValidation=s.fullHallValidation(validMask);
fullHallContract=s.fullHallContract;fullHallAudit=s.fullHallAudit;
assert(numel(fullHallTrain)>=128 && numel(fullHallValidation)>=128);
assert(numel(unique(string(cellfun(@(r)r.boot_id,fullHallTrain,UniformOutput=false))))==numel(fullHallContract.training_boot_ids));
assert(numel(unique(string(cellfun(@(r)r.boot_id,fullHallValidation,UniformOutput=false))))==numel(fullHallContract.validation_boot_ids));
fullHallContract.training_cohort="source-elapsed-at-least-10s-v1";
fullHallContract.minimum_source_elapsed_ms=10000;
fullHallContract.late_cohort_does_not_prove_steady_state=true;
fullHallContract.parent_input_sha256=motorFileSHA256(input);
fullHallContract.parent_training_normalizer_preserved=true;
fullHallContract.runtime_compatible=false;
fullHallAudit.unique_train_windows=numel(fullHallTrain);fullHallAudit.unique_validation_windows=numel(fullHallValidation);
fullHallAudit.measured_gain_switch_train_windows=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,fullHallTrain));
fullHallAudit.measured_gain_switch_validation_windows=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,fullHallValidation));
assert(fullHallAudit.measured_gain_switch_train_windows>=32 && fullHallAudit.measured_gain_switch_validation_windows>=32);
fullHallAudit.independent_full_hall_reward_checks=numel(fullHallTrain)+numel(fullHallValidation);
assert(isequal(fullHallTrain,s.fullHallTrain(trainMask)) && isequal(fullHallValidation,s.fullHallValidation(validMask)));
report=struct(passed=true,parent_unique_windows=numel(rows),selected_unique_windows=numel(fullHallTrain)+numel(fullHallValidation), ...
    training_windows=numel(fullHallTrain),validation_windows=numel(fullHallValidation), ...
    measured_training_switches=fullHallAudit.measured_gain_switch_train_windows, ...
    measured_validation_switches=fullHallAudit.measured_gain_switch_validation_windows, ...
    source_input_sha256=motorFileSHA256(input),component_proof=proof, ...
    selected_train_physical_keys=string(cellfun(@(r)r.physical_key,fullHallTrain,UniformOutput=false)), ...
    selected_validation_physical_keys=string(cellfun(@(r)r.physical_key,fullHallValidation,UniformOutput=false)), ...
    minimum_source_elapsed_ms=10000,fixed_selection_not_optimized_on_validation=true, ...
    parent_training_normalizer_preserved=true,original_rows_rewards_actions_and_masks_unchanged=true, ...
    whole_boot_split_unchanged=true,alternate_view_not_extra_physical_samples=true, ...
    hardware_accessed=false,training_performed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
save(output,'fullHallTrain','fullHallValidation','fullHallContract','fullHallAudit','report');
disp(jsonencode(rmfield(report,{'selected_train_physical_keys','selected_validation_physical_keys'})));
end
