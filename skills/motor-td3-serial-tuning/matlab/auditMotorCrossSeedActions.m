function report=auditMotorCrossSeedActions(input,study,output)
% Same-data twin agreement is not calibrated policy uncertainty or performance.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
assert(s.fullHallAudit.passed && motorFileSHA256(input)==string(summary.audited_input_sha256));
parts=cellfun(@(r)r.observation(:),s.fullHallValidation,UniformOutput=false);x=single(cat(2,parts{:}));
levels=unique(cellfun(@(r)r.action_normalized(1),s.fullHallTrain));baseline=find(levels==0);
assert(isscalar(baseline) && numel(summary.candidates)==3);
networks=cell(1,3);rank=zeros(3,size(x,2));actorActions=zeros(3,size(x,2));
for k=1:3
    c=summary.candidates(k);path=fullfile(study,"candidate-complete-Hall-seed-"+c.seed+".mat");
    assert(motorFileSHA256(path)==string(c.checkpoint_sha256));networks{k}=load(path,'trainingState','contract');
    t=networks{k}.trainingState;actions=extractdata(predict(t.actor,dlarray(x,'CB')));
    assert(all(actions(2,:)==0));actorActions(k,:)=double(actions(1,:));q=zeros(numel(levels),size(x,2));
    for j=1:numel(levels)
        action=single([repmat(levels(j),1,size(x,2));zeros(1,size(x,2))]);
        q(j,:)=min(predictQ(t.critic1,x,action),predictQ(t.critic2,x,action));
    end
    [~,rank(k,:)]=max(q,[],1);
end
medianAction=single([median(actorActions,1);zeros(1,size(x,2))]);advantage=zeros(3,size(x,2));
for k=1:3
    t=networks{k}.trainingState;base=single(zeros(2,size(x,2)));
    advantage(k,:)=min(predictQ(t.critic1,x,medianAction),predictQ(t.critic2,x,medianAction))- ...
        min(predictQ(t.critic1,x,base),predictQ(t.critic2,x,base));
end
report=struct(passed=true,validation_windows=size(x,2),seeds=[summary.candidates.seed], ...
    actual_supported_action_levels=levels,cross_seed_all_best_action_agreement=mean(all(rank==rank(1,:),1)), ...
    cross_seed_all_baseline_best_fraction=mean(all(rank==baseline,1)), ...
    fraction_median_suggestion_positive_for_all_three_seeds=mean(all(advantage>0,1)), ...
    mean_min_across_seed_median_suggestion_advantage=mean(min(advantage,[],1)), ...
    mean_median_suggestion_advantage_per_seed=mean(advantage,2), ...
    median_policy_was_not_trained_or_applied=true,same_physical_data_used_by_all_seeds=true, ...
    twin_or_seed_agreement_is_not_calibrated_uncertainty=true, ...
    counterfactual_Q_is_not_real_motor_performance=true,hardware_accessed=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function q=predictQ(net,x,a)
q=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
end
