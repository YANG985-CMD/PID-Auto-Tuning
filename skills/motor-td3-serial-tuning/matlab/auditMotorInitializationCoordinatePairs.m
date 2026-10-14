function report=auditMotorInitializationCoordinatePairs(source,study,output)
% Verify factorial arms use the same recorded experience and random updates.
arguments
    source (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));plan=jsondecode(fileread(fullfile(study,'study-summary.json')));
s=load(fullfile(source,'audited-input.mat'));
assert(plan.passed && plan.historical_arm_reproduction_max_parameter_error==0);
assert(motorFileSHA256(fullfile(source,'audited-input.mat'))==string(plan.contract.source_input_sha256));
assert(motorFileSHA256(fullfile(source,'replay/summary.json'))==string(plan.contract.source_replay_sha256));
trainBoots=sort(s.fullHallContract.training_boot_ids(:));validBoots=sort(s.fullHallContract.validation_boot_ids(:));
assert(isempty(intersect(trainBoots,validBoots)));rows=struct([]);
for seed=[7 17 27]
    rngReference=[];sampleReference=[];
    for entry=plan.studies(:)'
        stem=string(entry.critic_initialization)+"-"+string(entry.actor_lambda_coordinate);
        folder=fullfile(study,"train-"+stem);summary=jsondecode(fileread(fullfile(folder,'training-summary.json')));
        assert(motorFileSHA256(fullfile(folder,'training-summary.json'))==string(entry.source_summary_sha256));
        assert(string(summary.audited_input_sha256)==string(plan.contract.source_input_sha256));
        assert(string(summary.replay_manifest_sha256)==string(plan.contract.source_replay_sha256));
        row=summary.candidates([summary.candidates.seed]==seed);assert(isscalar(row));
        file=fullfile(folder,"candidate-complete-Hall-seed-"+seed+".mat");
        assert(motorFileSHA256(file)==string(row.checkpoint_sha256));c=load(file,'contract','trainingState','candidateReport');
        assert(isequal(c.contract.action_mask,[1 0]) && c.candidateReport.fixed_ki==.00144);
        assert(~c.candidateReport.candidate_admission && ~c.candidateReport.deployment_allowed && ~c.candidateReport.performance_claim_allowed);
        assert(c.candidateReport.critic_update_iterations==600 && c.candidateReport.actor_updates==300);
        assert(isequal(sort(c.contract.training_boot_ids(:)),trainBoots) && isequal(sort(c.contract.validation_boot_ids(:)),validBoots));
        if isempty(rngReference)
            rngReference=c.trainingState.rng_state;sampleReference=c.candidateReport.minibatch_action_sample_counts;
        else
            assert(isequal(c.trainingState.rng_state,rngReference));
            assert(isequal(c.candidateReport.minibatch_action_sample_counts,sampleReference));
        end
        initialization=c.candidateReport.critic_initialization_report;
        assert(~initialization.validation_data_used);
        if string(entry.critic_initialization)=="factual-ridge-bootstrap"
            assert(initialization.ridge_initialization_fits==2);
            assert(isequal(sort(initialization.training_boots),trainBoots));
            assert(initialization.twin_coefficient_distance>0 && ~initialization.bootstrap_is_calibrated_uncertainty);
        end
        value=struct(seed=seed,critic_initialization=string(entry.critic_initialization), ...
            lambda_coordinates=string(entry.actor_lambda_coordinate), ...
            final_lambda=c.candidateReport.final_training_actor_lambda, ...
            native_mean_abs_Q=c.candidateReport.final_training_policy_mean_abs_native_Q, ...
            scaling_mean_abs_Q=c.candidateReport.final_training_policy_mean_abs_scaling_Q, ...
            validation_target_residual_rmse=c.candidateReport.validation_target_residual_rmse, ...
            raw_kp_range=c.candidateReport.validation_raw_kp_range,checkpoint_sha256=string(row.checkpoint_sha256));
        if isempty(rows),rows=value;else,rows(end+1)=value;end %#ok<AGROW>
    end
end
report=struct(passed=true,candidate_checkpoints_verified=numel(rows),rows=rows, ...
    same_physical_data_boot_splits_and_update_RNG=true,train_only_ridge_initialization_verified=true, ...
    old_arm_reproduced_exactly=true,action_mask=[1 0],fixed_ki=.00144, ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(rmfield(report,'rows')));
end
