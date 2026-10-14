function report=auditMotorSamplingPolicyContrast(input,controlStudy,candidateStudy,output)
% Same-input frozen contrasts: fit by switch status and shared critic judges.
arguments
    input (1,1) string
    controlStudy (1,1) string
    candidateStudy (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
rows=s.fullHallValidation;parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
parts=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);actual=double(cat(2,parts{:}));
changed=cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,rows)';
policies=cell(1,6);actions=cell(1,6);meta=struct([]);index=0;
for folder=[controlStudy,candidateStudy]
    summary=jsondecode(fileread(fullfile(folder,'training-summary.json')));
    assert(string(summary.audited_input_sha256)==motorFileSHA256(input) && numel(summary.candidates)==3);
    for c=summary.candidates(:)'
        index=index+1;path=fullfile(folder,"candidate-complete-Hall-seed-"+c.seed+".mat");
        assert(motorFileSHA256(path)==string(c.checkpoint_sha256));p=load(path,'trainingState','contract');policies{index}=p;
        assert(~p.contract.runtime_compatible && p.contract.execution_wrapper_required);
        actions{index}=single(extractdata(motorTD3ExecutedAction(predict(p.trainingState.actor,dlarray(x,'CB')),x,p.contract)));
        assert(all(actions{index}(2,:)==0));
        row=struct(seed=c.seed,sampling=string(summary.actual_action_sampling),checkpoint_sha256=string(c.checkpoint_sha256), ...
            validation_residual_rmse=c.validation_target_residual_rmse);
        if isempty(meta),meta=row;else,meta(end+1)=row;end %#ok<AGROW>
    end
end
results=struct([]);allQ=cell(1,6);
for k=1:6
    q=zeros(6,numel(rows));
    for j=1:6
        assert(isequal(policies{j}.contract.state_center,policies{k}.contract.state_center));
        assert(isequal(policies{j}.contract.state_scale,policies{k}.contract.state_scale));
        q(j,:)=minQ(policies{j},x,actions{k});
    end
    allQ{k}=q;
end
scale=4;
for k=1:3
    assert(meta(k).seed==meta(k+3).seed);a=double(actions{k});b=double(actions{k+3});
    delta=allQ{k+3}-allQ{k};gainDifference=100*(b(1,:)-a(1,:))*.00054224/.003389;
    row=struct(seed=meta(k).seed,control_sampling=meta(k).sampling,candidate_sampling=meta(k+3).sampling, ...
        validation_hold_windows=sum(~changed),validation_switch_windows=sum(changed), ...
        control_hold_BC_loss=mean((scale*(a(1,~changed)-actual(1,~changed))).^2)/2, ...
        control_switch_BC_loss=mean((scale*(a(1,changed)-actual(1,changed))).^2)/2, ...
        candidate_hold_BC_loss=mean((scale*(b(1,~changed)-actual(1,~changed))).^2)/2, ...
        candidate_switch_BC_loss=mean((scale*(b(1,changed)-actual(1,changed))).^2)/2, ...
        mean_absolute_Kp_difference_percent=mean(abs(gainDifference)), ...
        six_judge_mean_predicted_advantage=mean(delta,2)', ...
        all_judges_positive_mean=all(mean(delta,2)>0), ...
        all_judges_positive_state_fraction=mean(all(delta>0,1)), ...
        control_validation_residual_rmse=meta(k).validation_residual_rmse, ...
        candidate_validation_residual_rmse=meta(k+3).validation_residual_rmse);
    if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
end
report=struct(passed=true,results=results,unique_validation_windows=numel(rows), ...
    matched_seed_and_input=true,shared_six_frozen_judges=true, ...
    learned_Q_is_not_measured_control_performance=true, ...
    repeated_sampling_does_not_add_physical_evidence=true, ...
    training_performed=false,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
function q=minQ(p,x,a)
q1=extractdata(predict(p.trainingState.critic1,dlarray(x,'CB'),dlarray(a,'CB')));
q2=extractdata(predict(p.trainingState.critic2,dlarray(x,'CB'),dlarray(a,'CB')));
q=double(min(q1,q2));
end
