function report=diagnoseMotorFullHallCritics(auditedInput,studies,output)
% Freeze all weights. Counterfactual Q values are diagnostics, not motor data.
arguments
    auditedInput (1,1) string
    studies (:,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(auditedInput);assert(s.fullHallAudit.passed);
values=cellfun(@(r)r.observation(:),s.fullHallValidation,UniformOutput=false);
x=single(cat(2,values{:}));levels=unique(cellfun(@(r)r.action_normalized(1),s.fullHallTrain));
assert(any(numel(levels)==[3 4]));baselineIndex=find(levels==0);assert(isscalar(baselineIndex));rows=struct([]);
for study=studies'
    summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
    assert(summary.audited_input_sha256==motorFileSHA256(auditedInput));
    for candidate=summary.candidates(:)'
        file=fullfile(study,"candidate-"+string(candidate.reward_mode)+"-seed-"+candidate.seed+".mat");
        assert(motorFileSHA256(file)==string(candidate.checkpoint_sha256));
        c=load(file,'trainingState','contract');q=zeros(2,numel(levels),size(x,2));
        nets={c.trainingState.critic1,c.trainingState.critic2};
        for critic=1:2
            for action=1:numel(levels)
                a=single([repmat(levels(action),1,size(x,2));zeros(1,size(x,2))]);
                q(critic,action,:)=reshape(double(extractdata(predict(nets{critic},dlarray(x,'CB'),dlarray(a,'CB')))),1,1,[]);
            end
        end
        [~,r1]=max(reshape(q(1,:,:),numel(levels),[]),[],1);[~,r2]=max(reshape(q(2,:,:),numel(levels),[]),[],1);
        minimum=reshape(min(q,[],1),numel(levels),[]);[~,choice]=max(minimum,[],1);
        actorAction=predict(c.trainingState.actor,dlarray(x,'CB'));
        assert(all(extractdata(actorAction(2,:))==0));
        aq=zeros(2,size(x,2));
        for critic=1:2,aq(critic,:)=double(extractdata(predict(nets{critic},dlarray(x,'CB'),actorAction)));end
        valueShift=0;
        if isfield(c.contract,'q_value_shift'),valueShift=c.contract.q_value_shift;end
        assert(isscalar(valueShift) && isfinite(valueShift));
        advantage=min(aq,[],1)-minimum(baselineIndex,:);
        valueCoordinates="original physical reward value";
        if isfield(c.contract,'learning_reward_profile'),valueCoordinates="unshifted "+string(c.contract.learning_reward_profile)+" value";end
        row=struct(sampling=string(summary.actual_action_sampling),seed=candidate.seed, ...
            actual_supported_action_levels=levels,validation_states=size(x,2), ...
            min_twin_best_action_counts=arrayfun(@(index)sum(choice==index),1:numel(levels)), ...
            baseline_action_index=baselineIndex, ...
            twin_ranking_agreement_fraction=mean(r1==r2),mean_Q_by_actual_action=squeeze(mean(q,3))-valueShift, ...
            native_critic_value_shift_C=valueShift,Q_value_report_coordinates=valueCoordinates, ...
            mean_predicted_Actor_advantage_over_baseline=mean(advantage), ...
            fraction_predicted_Actor_advantage_positive=mean(advantage>0), ...
            mean_twin_disagreement=mean(abs(reshape(q(1,:,:)-q(2,:,:),numel(levels),[])),'all'), ...
            checkpoint_sha256=motorFileSHA256(file));
        if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
        disp(jsonencode(row));
    end
end
report=struct(passed=true,results=rows,hardware_accessed=false,weights_changed=false, ...
    Q_values_are_physical_performance=false, ...
    validation_boots=s.fullHallContract.validation_boot_ids, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
end
