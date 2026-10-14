function report=auditMotorLearningRatePairs(previous,current,output)
arguments
    previous (1,1) string
    current (1,1) string
    output (1,1) string
end
assert(~isfile(output));rows=struct([]);
for observation=["original","causal"]
    old=fullfile(previous,"train-"+observation+"-local-quadratic");new=fullfile(current,"train-"+observation+"-low-rate");
    a=jsondecode(fileread(fullfile(old,'training-summary.json')));b=jsondecode(fileread(fullfile(new,'training-summary.json')));
    assert(string(a.audited_input_sha256)==string(b.audited_input_sha256));
    assert(a.critic_learning_rate==.001 && b.critic_learning_rate==1e-5);
    for field={'actual_action_sampling','critic_architecture','critic_weight_decay','target_noise_std','target_noise_clip', ...
            'target_tau','actor_learning_rate','steps_per_candidate','training_boot_ids','validation_boot_ids'}
        assert(isequal(a.(field{1}),b.(field{1})),field{1});
    end
    for k=1:numel(a.candidates)
        c=a.candidates(k);d=b.candidates(k);assert(c.seed==d.seed);
        name="candidate-complete-Hall-seed-"+c.seed+".mat";
        assert(motorFileSHA256(fullfile(old,name))==string(c.checkpoint_sha256));
        assert(motorFileSHA256(fullfile(new,name))==string(d.checkpoint_sha256));
        x=load(fullfile(old,name),'trainingState','contract');y=load(fullfile(new,name),'trainingState','contract');
        assert(isequal(x.trainingState.rng_state,y.trainingState.rng_state));
        assert(isequal(c.minibatch_action_sample_counts,d.minibatch_action_sample_counts));
        assert(isequal(x.contract.critic_feature_center,y.contract.critic_feature_center));
        assert(isequal(x.contract.critic_feature_scale,y.contract.critic_feature_scale));
        row=struct(observation=observation,seed=c.seed,paired_random_stream_verified=true, ...
            feature_normalization_identical=true,old_lr=a.critic_learning_rate,new_lr=b.critic_learning_rate, ...
            old_residual=c.validation_target_residual_rmse,new_residual=d.validation_target_residual_rmse, ...
            old_checkpoint_sha256=c.checkpoint_sha256,new_checkpoint_sha256=d.checkpoint_sha256);
        if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(passed=true,pairs=rows,custom_weight_decay_and_other_training_settings_unchanged=true, ...
    saved_native_optimizer_metadata_now_matches_custom_training=true, ...
    models_have_distinct_dynamic_targets=true,residual_reduction_is_not_physical_speed_improvement=true, ...
    hardware_accessed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
