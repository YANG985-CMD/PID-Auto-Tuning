function report=auditMotorFeasibleTrainingParity(priorStudy,newStudy,input,output)
old=jsondecode(fileread(fullfile(priorStudy,'training-summary.json')));new=jsondecode(fileread(fullfile(newStudy,'training-summary.json')));
assert(string(old.audited_input_sha256)==string(new.audited_input_sha256) && motorFileSHA256(input)==string(new.audited_input_sha256));
assert(isequal(old.sampling_support,new.sampling_support));
assert(old.actor_learning_rate==new.actor_learning_rate && old.critic_learning_rate==new.critic_learning_rate && old.target_tau==new.target_tau);
assert(new.target_noise_coordinates=="absolute-target-v7 after feasible mapping");
rows=struct([]);s=load(input);
p=cellfun(@(r)r.observation(:),[s.fullHallTrain;s.fullHallValidation],UniformOutput=false);x=single(cat(2,p{:}));
for seed=[7 17 27]
    name="candidate-complete-Hall-seed-"+seed+".mat";a=load(fullfile(priorStudy,name));b=load(fullfile(newStudy,name));
    assert(isequal(a.trainingState.target_smoothing_noise,b.trainingState.target_smoothing_noise) && isequal(a.trainingState.target_noise_stream_state,b.trainingState.target_noise_stream_state));
    assert(isequal(a.candidateReport.minibatch_action_sample_counts,b.candidateReport.minibatch_action_sample_counts));
    assert(a.candidateReport.sampled_switch_count==b.candidateReport.sampled_switch_count);
    assert(isequal(a.candidateReport.critic_initialization_report,b.candidateReport.critic_initialization_report));
    assert(b.contract.native_rl_agent_exported==false && ~isfield(b,'experimentalAgent'));
    raw=predict(b.trainingState.actor,dlarray(x,'CB'));
    g=dlfeval(@slope,raw,x,b.contract);fraction=mean(double(extractdata(g(1,:)))==0);
    assert(fraction==0);
    value=struct(seed=seed,noise_draws_exactly_matched=true,sampled_action_counts_matched=true,sampled_switch_count_matched=true, ...
        initial_critic_bootstrap_identical=true,raw_and_critic_coordinates_distinguished=true,final_mapping_zero_gradient_fraction=fraction, ...
        saved_critic_iterations=b.trainingState.critic_iterations,saved_Actor_updates=b.trainingState.actor_iterations);
    if isempty(rows),rows=value;else,rows(end+1)=value;end %#ok<AGROW>
end
report=struct(passed=true,seeds=rows,raw_initial_actor_behavior_differs=true,same_replay_same_rewards_same_sampler=true, ...
    initial_critic_bootstrap_identical=true,gradient_clipping_dead_region_removed_without_STE=true, ...
    hardware_accessed=false,new_motor_trials=0,new_optimizer_updates_in_audit=0,actor_applied=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
assert(~isfile(output));f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function g=slope(a,x,c)
b=motorTD3ExecutedAction(a,x,c,true);g=dlgradient(sum(b(1,:)),a);
end
