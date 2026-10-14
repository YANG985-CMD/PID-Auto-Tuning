function report=auditMotorCohortPolicyContrast(input,fullStudy,lateStudy,output)
% Compare fixed policies on common late states with six shared twin judges.
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
oldSummary=jsondecode(fileread(fullfile(fullStudy,'training-summary.json')));
newSummary=jsondecode(fileread(fullfile(lateStudy,'training-summary.json')));
assert(motorFileSHA256(input)==string(newSummary.audited_input_sha256));
assert(numel(oldSummary.candidates)==3 && numel(newSummary.candidates)==3);
for field=["trainer_source_sha256","actual_action_sampling","steps_per_candidate","actor_learning_rate", ...
        "critic_learning_rate","critic_weight_decay","actor_actual_gain_feature","execution_mode", ...
        "actor_lambda_value_coordinates","training_seed_mode","target_noise_source"]
    assert(isequal(oldSummary.(field),newSummary.(field)));
end
assert(isequal(oldSummary.seeds,newSummary.seeds) && isequal(newSummary.seeds(:)',[7 17 27]));
rows=s.fullHallValidation;parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
parts=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);actual=single(cat(2,parts{:}));
switched=cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,rows)';
old=cell(1,3);late=old;before=old;after=old;policy=struct([]);
judgeSeeds=[7 17 27];
for k=1:3
    seed=newSummary.candidates(k).seed;assert(oldSummary.candidates(k).seed==seed);
    name="candidate-complete-Hall-seed-"+seed+".mat";
    aPath=fullfile(fullStudy,name);bPath=fullfile(lateStudy,name);
    assert(motorFileSHA256(aPath)==string(oldSummary.candidates(k).checkpoint_sha256));
    assert(motorFileSHA256(bPath)==string(newSummary.candidates(k).checkpoint_sha256));
    old{k}=load(aPath,'trainingState','contract');late{k}=load(bPath,'trainingState','contract');
    a=old{k};b=late{k};
    assert(isequal(a.contract.state_center,b.contract.state_center) && isequal(a.contract.state_scale,b.contract.state_scale));
    assert(isequal(a.contract.actor_input_mask,b.contract.actor_input_mask) && isequal(a.contract.action_mask,[1 0]));
    before{k}=double(extractdata(motorTD3ExecutedAction(predict(a.trainingState.actor,dlarray(x,'CB')),x,a.contract)));
    after{k}=double(extractdata(motorTD3ExecutedAction(predict(b.trainingState.actor,dlarray(x,'CB')),x,b.contract)));
    assert(all(before{k}(2,:)==0 & after{k}(2,:)==0));
    assert(isequal(a.trainingState.target_smoothing_noise,b.trainingState.target_smoothing_noise));
    actualSource=cellfun(@(r)r.actual_source_kp,rows)';
    gains=double(single(b.contract.encoded_baseline_gains(1)+b.contract.gain_step_scale(1)*after{k}(1,:)));
    assert(all(abs(gains-actualSource)<=.00013556+1e-9));
    value=struct(seed=seed,old_checkpoint_sha256=string(oldSummary.candidates(k).checkpoint_sha256), ...
        late_checkpoint_sha256=string(newSummary.candidates(k).checkpoint_sha256), ...
        full_cohort_actor_imitation_MSE=mean((4*(before{k}(1,:)-double(actual(1,:)))).^2), ...
        late_actor_imitation_MSE=mean((4*(after{k}(1,:)-double(actual(1,:)))).^2), ...
        full_cohort_actor_switch_imitation_MSE=mean((4*(before{k}(1,switched)-double(actual(1,switched)))).^2), ...
        late_actor_switch_imitation_MSE=mean((4*(after{k}(1,switched)-double(actual(1,switched)))).^2), ...
        mean_absolute_executed_Kp_difference_percent=100*mean(abs(after{k}(1,:)-before{k}(1,:)))*b.contract.gain_step_scale(1)/.003389, ...
        late_executed_Kp_range=[min(gains),max(gains)],action_bounds_and_Ki_passed=true);
    if isempty(policy),policy=value;else,policy(end+1)=value;end %#ok<AGROW>
end
judges=[old late];comparison=struct([]);advantages=zeros(6,3);
for j=1:6
    p=judges{j};nets={p.trainingState.critic1,p.trainingState.critic2};
    for k=1:3
        qa=zeros(2,numel(rows));qb=qa;
        for q=1:2
            qa(q,:)=double(extractdata(predict(nets{q},dlarray(x,'CB'),dlarray(single(before{k}),'CB'))));
            qb(q,:)=double(extractdata(predict(nets{q},dlarray(x,'CB'),dlarray(single(after{k}),'CB'))));
        end
        delta=min(qb,[],1)-min(qa,[],1);advantages(j,k)=mean(delta);
        kind="full-cohort";if j>3,kind="late-cohort";end
        value=struct(judge_cohort=kind,judge_seed=judgeSeeds(mod(j-1,3)+1), ...
            policy_seed=policy(k).seed,mean_predicted_late_minus_full_advantage=mean(delta), ...
            mean_hold_predicted_advantage=mean(delta(~switched)),mean_switch_predicted_advantage=mean(delta(switched)), ...
            positive_predicted_fraction=mean(delta>0));
        if isempty(comparison),comparison=value;else,comparison(end+1)=value;end %#ok<AGROW>
    end
end
report=struct(passed=true,input_sha256=motorFileSHA256(input),validation_windows=numel(rows), ...
    actual_switch_validation_windows=nnz(switched),policies=policy,shared_judges=comparison, ...
    all_shared_judges_positive_by_policy_seed=all(advantages>0,1), ...
    controls_have_identical_trainer_and_target_noise=true, ...
    Q_is_one_step_under_each_judges_future_policy=true, ...
    physical_speed_RMSE_improvement_percent=NaN, ...
    independent_frozen_actor_response_verified=false,counterfactual_Q_is_not_measured_motor_performance=true, ...
    hardware_accessed=false,actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(struct(passed=true,policies=policy,all_shared_judges_positive=all(advantages>0,1))));
end
