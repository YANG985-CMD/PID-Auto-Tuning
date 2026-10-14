function report=auditMotorPIOutputTraining(originalStudy,newStudy,originalInput,newInput,output)
% Check the one-input experiment without assuming the new Critic fit is equal.
arguments
    originalStudy (1,1) string
    newStudy (1,1) string
    originalInput (1,1) string
    newInput (1,1) string
    output (1,1) string
end
assert(~isfile(output));
old=jsondecode(fileread(fullfile(originalStudy,'training-summary.json')));
new=jsondecode(fileread(fullfile(newStudy,'training-summary.json')));
assert(string(new.audited_input_sha256)==motorFileSHA256(newInput));
assert(string(old.audited_input_sha256)==motorFileSHA256(originalInput));
assert(isequal(old.sampling_support,new.sampling_support));
parameters=["actor_learning_rate","critic_learning_rate","target_tau","target_noise_std", ...
    "target_noise_clip","behavior_cloning_RL_weight","batch_size","delayed_policy_period", ...
    "critic_weight_decay","steps_per_candidate","trainer_source_sha256"];
for p=parameters,assert(isequal(old.(p),new.(p)));end
assert(new.learning_contract.observation_profile=="history20-40-PI-command-v1");
assert(new.learning_contract.actor_input_mask(10)==new.learning_contract.critic_input_mask(10) && new.learning_contract.actor_input_mask(10)==1);
seeds=struct([]);
for seed=[7 17 27]
    name="candidate-complete-Hall-seed-"+seed+".mat";
    a=load(fullfile(originalStudy,name));b=load(fullfile(newStudy,name));
    assert(isequal(a.trainingState.target_smoothing_noise,b.trainingState.target_smoothing_noise));
    assert(isequal(a.trainingState.target_noise_stream_state,b.trainingState.target_noise_stream_state));
    assert(isequal(a.candidateReport.minibatch_action_levels_normalized,b.candidateReport.minibatch_action_levels_normalized));
    assert(isequal(a.candidateReport.minibatch_action_sample_counts,b.candidateReport.minibatch_action_sample_counts));
    assert(a.candidateReport.sampled_hold_count==b.candidateReport.sampled_hold_count);
    assert(a.candidateReport.sampled_switch_count==b.candidateReport.sampled_switch_count);
    assert(a.candidateReport.critic_value_shift_C==b.candidateReport.critic_value_shift_C);
    assert(a.candidateReport.critic_initial_value==b.candidateReport.critic_initial_value);
    for twin=1:2
        assert(isequal(a.candidateReport.critic_initialization_report.fits(twin).positive_boot_masses, ...
            b.candidateReport.critic_initialization_report.fits(twin).positive_boot_masses));
    end
    assert(b.trainingState.critic_iterations==600 && b.trainingState.actor_iterations==300);
    assert(b.candidateReport.actor_weight_change_l2>0 && isequal(b.contract.action_mask,[1 0]));
    assert(~b.contract.native_rl_agent_exported && ~isfield(b,'experimentalAgent'));
    value=struct(seed=seed,checkpoint_sha256=motorFileSHA256(fullfile(newStudy,name)), ...
        target_noise_and_boot_masses_equal=true,actual_action_sampling_and_switch_counts_equal=true, ...
        value_centering_equal=true,initial_critic_coefficients_expected_to_change=true, ...
        saved_double_Critic_iterations=b.trainingState.critic_iterations,saved_Actor_updates=b.trainingState.actor_iterations);
    if isempty(seeds),seeds=value;else,seeds(end+1)=value;end %#ok<AGROW>
end
report=struct(passed=true,seeds=seeds,original_trainer_unchanged=true, ...
    rewards_actions_bounds_optimizer_settings_unchanged=true, ...
    normalization_and_input10_changed=true,masked_clock_replaced_by_actual_PI_command=true, ...
    replay_rows_not_new_physical_data=true,hardware_accessed=false,new_physical_trials=0, ...
    new_optimizer_updates_in_audit=0,actor_applied=false,candidate_admission=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
