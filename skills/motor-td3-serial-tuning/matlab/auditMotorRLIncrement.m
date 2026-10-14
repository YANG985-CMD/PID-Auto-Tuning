function report=auditMotorRLIncrement(input,studies,output)
% Compare frozen RL and BC-only actors under the same frozen critics.
% Q differences are diagnostics, not measured closed-loop performance.
arguments
    input (1,1) string
    studies (:,1) string
    output (1,1) string
end
assert(~isfile(output) && numel(studies)>=2);s=load(input);assert(s.fullHallAudit.passed);
rows=s.fullHallValidation;v=cellfun(@(r)r.observation(:),rows,UniformOutput=false);
x=single(cat(2,v{:}));boot=string(cellfun(@(r)r.boot_id,rows,UniformOutput=false));
count=3*numel(studies);
policies=cell(count,1);meta=struct([]);actions=cell(count,1);hashes=strings(count,1);paths=hashes;
index=0;
for study=studies'
    summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
    assert(string(summary.audited_input_sha256)==motorFileSHA256(input));
    assert(summary.actor_learning_rate==.001 && numel(summary.candidates)==3);
    for candidate=summary.candidates(:)'
        index=index+1;paths(index)=fullfile(study,"candidate-complete-Hall-seed-"+candidate.seed+".mat");
        hashes(index)=motorFileSHA256(paths(index));assert(hashes(index)==string(candidate.checkpoint_sha256));
        p=load(paths(index),'trainingState','contract');policies{index}=p;
        assert(p.contract.execution_wrapper_required && ~p.contract.runtime_compatible);
        a=motorTD3ExecutedAction(predict(p.trainingState.actor,dlarray(x,'CB')),dlarray(x,'CB'),p.contract);
        actions{index}=single(extractdata(a));assert(all(actions{index}(2,:)==0));
        row=struct(study=study,seed=candidate.seed,RL_weight=summary.behavior_cloning_RL_weight, ...
            validation_target_residual_rmse=candidate.validation_target_residual_rmse,checkpoint_sha256=hashes(index));
        if isempty(meta),meta=row;else,meta(end+1)=row;end %#ok<AGROW>
    end
end
assert(sum([meta.RL_weight]==0)==3 && any([meta.RL_weight]>0));
results=struct([]);selfError=0;
for i=find([meta.RL_weight]>0)
    reference=find([meta.RL_weight]==0 & [meta.seed]==meta(i).seed);assert(isscalar(reference));
    deltas=zeros(count,numel(rows));judges=struct([]);
    for j=1:count
        p=policies{j};qa=minQ(p,x,actions{i});qb=minQ(p,x,actions{reference});
        selfError=max(selfError,max(abs(qb-minQ(p,x,actions{reference}))));
        deltas(j,:)=qa-qb;
        value=struct(seed=meta(j).seed,RL_weight=meta(j).RL_weight, ...
            mean_predicted_RL_minus_BC_advantage=mean(deltas(j,:)), ...
            positive_fraction=mean(deltas(j,:)>0), ...
            critic_validation_residual_rmse=meta(j).validation_target_residual_rmse);
        if isempty(judges),judges=value;else,judges(end+1)=value;end %#ok<AGROW>
    end
    byBoot=struct([]);
    for b=unique(boot(:))'
        mask=boot==b;value=struct(boot_id=b,windows=sum(mask), ...
            mean_advantage_across_judges=mean(deltas(:,mask),'all'), ...
            minimum_judge_mean_advantage=min(mean(deltas(:,mask),2)), ...
            maximum_judge_mean_advantage=max(mean(deltas(:,mask),2)));
        if isempty(byBoot),byBoot=value;else,byBoot(end+1)=value;end %#ok<AGROW>
    end
    relativeDelta=100*double(actions{i}(1,:)-actions{reference}(1,:))*.00054224/.003389;
    value=struct(seed=meta(i).seed,RL_weight=meta(i).RL_weight, ...
        mean_absolute_Kp_difference_from_BC_percent=mean(abs(relativeDelta)), ...
        maximum_absolute_Kp_difference_from_BC_percent=max(abs(relativeDelta)), ...
        all_judges_positive_mean=all(mean(deltas,2)>0), ...
        all_judges_positive_state_fraction=mean(all(deltas>0,1)), ...
        judges=judges,by_validation_boot=byBoot);
    if isempty(results),results=value;else,results(end+1)=value;end %#ok<AGROW>
end
assert(selfError==0);
for k=1:count,assert(motorFileSHA256(paths(k))==hashes(k));end
report=struct(passed=true,results=results,unique_validation_windows=numel(rows), ...
    validation_boots=unique(boot(:)),judge_count=count,checkpoint_hashes_unchanged=true, ...
    identical_action_Q_difference_max_abs=selfError,matched_same_seed_BC_control=true, ...
    same_judge_used_for_both_actions=true,validation_only=true, ...
    critic_residual_is_not_calibrated_counterfactual_uncertainty=true, ...
    critics_are_correlated_and_not_independent_performance_tests=true, ...
    training_performed=false,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(struct(passed=true,policies_compared=numel(results),judges=count,validation_windows=numel(rows))));
end
function q=minQ(p,x,a)
q1=extractdata(predict(p.trainingState.critic1,dlarray(x,'CB'),dlarray(a,'CB')));
q2=extractdata(predict(p.trainingState.critic2,dlarray(x,'CB'),dlarray(a,'CB')));
q=double(min(q1,q2));
end
