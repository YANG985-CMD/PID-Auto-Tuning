function report=auditMotorFullIntervalPairs(previous,current,output)
arguments
    previous (1,1) string
    current (1,1) string
    output (1,1) string
end
assert(~isfile(output));rows=struct([]);
for observation=["original","causal"]
    originalInput="audited-input.mat";if observation=="causal",originalInput="causal-input.mat";end
    oldInput=load(fullfile(previous,originalInput));newInput=load(fullfile(current,"full-"+observation+"-input.mat"));
    for field={'state_center','state_scale','training_boot_ids','validation_boot_ids','action_coordinate_version'}
        assert(isequal(oldInput.fullHallContract.(field{1}),newInput.fullHallContract.(field{1})),field{1});
    end
    for split={'fullHallTrain','fullHallValidation'}
        a=oldInput.(split{1});b=newInput.(split{1});assert(numel(a)==numel(b));
        for k=1:numel(a)
            for field={'physical_key','observation','next_observation','action_normalized','actual_source_kp','actual_target_kp','duration_us','legacy_time_reward'}
                assert(isequal(a{k}.(field{1}),b{k}.(field{1})),field{1});
            end
            assert(a{k}.reward==b{k}.post_ack_reward);
        end
    end
    old=fullfile(previous,"train-"+observation+"-observed");new=fullfile(current,"train-"+observation+"-full");
    a=jsondecode(fileread(fullfile(old,'training-summary.json')));b=jsondecode(fileread(fullfile(new,'training-summary.json')));
    for field={'critic_learning_rate','critic_weight_decay','actual_action_sampling','actor_actual_gain_feature', ...
            'training_seed_mode','target_tau','target_noise_std','target_noise_clip','actor_learning_rate'}
        assert(isequal(a.(field{1}),b.(field{1})),field{1});
    end
    for k=1:numel(a.candidates)
        c=a.candidates(k);d=b.candidates(k);assert(c.seed==d.seed);
        file="candidate-complete-Hall-seed-"+c.seed+".mat";
        assert(motorFileSHA256(fullfile(old,file))==string(c.checkpoint_sha256));
        assert(motorFileSHA256(fullfile(new,file))==string(d.checkpoint_sha256));
        x=load(fullfile(old,file),'trainingState');y=load(fullfile(new,file),'trainingState');
        assert(isequal(x.trainingState.rng_state,y.trainingState.rng_state));
        assert(isequal(c.minibatch_action_sample_counts,d.minibatch_action_sample_counts));
        row=struct(observation=observation,seed=c.seed,random_stream_and_action_counts_identical=true, ...
            old_checkpoint_sha256=c.checkpoint_sha256,new_checkpoint_sha256=d.checkpoint_sha256, ...
            old_learning_reward_profile="post-ACK-complete-Hall-v1", ...
            new_learning_reward_profile=d.learning_reward_profile, ...
            new_original_physical_rewards_unchanged=d.original_physical_rewards_unchanged);
        if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(passed=true,pairs=rows,source_states_actual_actions_next_states_preserved=true, ...
    old_rewards_retained_exactly=true,whole_boot_split_and_normalization_preserved=true, ...
    reward_definition_and_derived_value_shift_changed=true, ...
    reward_profile_scores_not_physical_performance_comparison=true, ...
    hardware_accessed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
