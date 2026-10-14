function report=auditMotorUpper8Execution(input,study,output)
% Frozen policy plus explicit mapper diagnostics; no substitute physical data.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
spec=motorStreamGainSpec("upper8-fullhall");rows=s.fullHallValidation;
parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
actual=cellfun(@(r)r.actual_source_kp,rows)';
plan=jsondecode(fileread(fullfile(study,'study-summary.json')));results=struct([]);
for entry=plan.studies(:)'
    stem=string(entry.critic_initialization)+"-"+string(entry.actor_lambda_coordinate);
    folder=fullfile(study,"train-"+stem);summary=jsondecode(fileread(fullfile(folder,'training-summary.json')));
    assert(string(summary.audited_input_sha256)==motorFileSHA256(input));
    for c=summary.candidates(:)'
        path=fullfile(folder,"candidate-complete-Hall-seed-"+c.seed+".mat");
        assert(motorFileSHA256(path)==string(c.checkpoint_sha256));p=load(path,'contract','trainingState');
        suggestion=double(extractdata(predict(p.trainingState.actor,dlarray(x,'CB'))));
        desired=double(single(.003389))+double(single(.00054224))*suggestion(1,:);
        [executed,kp,mapping]=motorUpper8ExecutionMap(suggestion,actual);
        % Baseline is also mapped through the same actual-ACK step. Compare
        % only executable actions, without replacing recorded experiences.
        [base,baseKp]=motorUpper8ExecutionMap(zeros(2,numel(actual)),actual);
        qRaw=zeros(2,numel(actual));qMapped=qRaw;qBase=qRaw;
        critics={p.trainingState.critic1,p.trainingState.critic2};
        for j=1:2
            qRaw(j,:)=predictQ(critics{j},x,single(suggestion));
            qMapped(j,:)=predictQ(critics{j},x,single(executed));
            qBase(j,:)=predictQ(critics{j},x,single(base));
        end
        exact=ismember(double(single(desired)),spec.exact_kp_levels);
        advantage=min(qMapped,[],1)-min(qBase,[],1);
        value=struct(seed=c.seed,critic_initialization=string(entry.critic_initialization), ...
            lambda_coordinates=string(entry.actor_lambda_coordinate),validation_windows=numel(actual), ...
            raw_actor_exact_allowlisted_fraction=mean(exact),raw_actor_requires_bridge_fraction=mapping.requires_bridge_count/numel(actual), ...
            proposed_mapped_action_counts=arrayfun(@(level)sum(kp==level),spec.exact_kp_levels), ...
            proposed_baseline_restore_action_counts=arrayfun(@(level)sum(baseKp==level),spec.exact_kp_levels), ...
            proposed_mapped_fraction_changes_gain=mean(kp~=actual), ...
            mean_predicted_mapped_advantage_over_reachable_baseline=mean(advantage), ...
            predicted_mapped_advantage_positive_fraction=mean(advantage>0), ...
            mean_raw_to_mapped_min_Q_change=mean(min(qMapped,[],1)-min(qRaw,[],1)), ...
            candidate_checkpoint_sha256=string(c.checkpoint_sha256), ...
            network_plus_mapper_is_a_different_unvalidated_policy=true, ...
            original_training_and_weights_unchanged=true);
        if isempty(results),results=value;else,results(end+1)=value;end %#ok<AGROW>
    end
end
report=struct(passed=true,results=results,mapping_version="upper8-exact-readback-nearest-feasible-hold-ties-v1", ...
    original_actor_raw_outputs_not_directly_allowed=true,hardware_actor_application_allowed=false, ...
    mapped_Q_is_not_measured_policy_performance=true,validation_data_used_for_diagnostic_only=true, ...
    training_updates=0,new_physical_windows=0,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(rmfield(report,'results')));
end
function q=predictQ(net,x,a)
q=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
end
