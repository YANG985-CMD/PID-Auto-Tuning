function report=auditMotorCriticStudyPairs(root)
arguments
    root (1,1) string
end
assert(jsondecode(fileread(fullfile(root,'architecture-study-summary.json'))).passed);
results=struct([]);
for observation=["original","causal"]
    left=fullfile(root,"train-"+observation+"-concat-mlp");right=fullfile(root,"train-"+observation+"-local-quadratic");
    a=jsondecode(fileread(fullfile(left,'training-summary.json')));
    b=jsondecode(fileread(fullfile(right,'training-summary.json')));
    assert(string(a.audited_input_sha256)==string(b.audited_input_sha256));
    assert(isequal(a.training_boot_ids,b.training_boot_ids) && isequal(a.validation_boot_ids,b.validation_boot_ids));
    assert(isequal(a.seeds,b.seeds) && string(a.training_seed_mode)=="isolated-update-stream" && string(b.training_seed_mode)=="isolated-update-stream");
    for k=1:numel(a.candidates)
        c=a.candidates(k);d=b.candidates(k);assert(c.seed==d.seed);
        filename="candidate-complete-Hall-seed-"+c.seed+".mat";
        assert(motorFileSHA256(fullfile(left,filename))==string(c.checkpoint_sha256));
        assert(motorFileSHA256(fullfile(right,filename))==string(d.checkpoint_sha256));
        x=load(fullfile(left,filename),'trainingState');y=load(fullfile(right,filename),'trainingState');
        rngEqual=isequal(x.trainingState.rng_state,y.trainingState.rng_state);
        sampleCountsEqual=isequal(c.minibatch_action_sample_counts,d.minibatch_action_sample_counts);
        assert(rngEqual && sampleCountsEqual,'MotorTD3:Pairing','Paired training random stream differs');
        row=struct(observation=observation,seed=c.seed,final_random_states_identical=rngEqual, ...
            action_sample_counts_identical=sampleCountsEqual, ...
            MLP_validation_residual=c.validation_target_residual_rmse, ...
            quadratic_validation_residual=d.validation_target_residual_rmse, ...
            residuals_use_each_models_own_target=true, ...
            MLP_Kp_range=c.validation_raw_kp_range,quadratic_Kp_range=d.validation_raw_kp_range, ...
            MLP_sha256=c.checkpoint_sha256,quadratic_sha256=d.checkpoint_sha256);
        if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(passed=true,paired_candidates=results,action_and_target_noise_draws_use_same_seeded_algorithm=true, ...
    validation_critic_targets_not_identical_across_architectures=true, ...
    residual_comparison_is_diagnostic_only=true, ...
    local_variant_changes_structure_and_regularization_together=true,hardware_accessed=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
path=fullfile(root,'paired-training-audit.json');assert(~isfile(path));
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
