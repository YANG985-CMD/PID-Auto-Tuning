function report=diagnoseMotorActorGainDependence(input,study,output)
% Conditional feature sensitivity, not a causal motor intervention.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
assert(s.fullHallAudit.passed && string(summary.audited_input_sha256)==motorFileSHA256(input));
values=cellfun(@(r)r.observation(:),s.fullHallValidation,UniformOutput=false);
x=single(cat(2,values{:}));rows=struct([]);
for candidate=summary.candidates(:)'
    file=fullfile(study,"candidate-"+string(candidate.reward_mode)+"-seed-"+candidate.seed+".mat");
    assert(motorFileSHA256(file)==string(candidate.checkpoint_sha256));c=load(file,'trainingState','contract');
    normal=double(extractdata(predict(c.trainingState.actor,dlarray(x,'CB'))));
    baseline=s.fullHallContract.encoded_baseline_gains(1)/.003389;
    fixed=x;fixed(8,:)=single(max(-5,min(5,(baseline-c.contract.state_center(8))/c.contract.state_scale(8))));
    changed=double(extractdata(predict(c.trainingState.actor,dlarray(fixed,'CB'))));
    ratio=var(changed(1,:))/max(var(normal(1,:)),eps);
    row=struct(seed=candidate.seed,validation_states=size(x,2), ...
        normalized_action_std=std(normal(1,:)),fixed_actual_kp_action_std=std(changed(1,:)), ...
        variance_remaining_after_fixing_actual_gain=ratio, ...
        mean_absolute_Kp_change=c.contract.gain_step_scale(1)*mean(abs(changed(1,:)-normal(1,:))), ...
        checkpoint_sha256=motorFileSHA256(file));
    if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
end
report=struct(passed=true,results=rows,hardware_accessed=false,weights_changed=false, ...
    feature_intervention_is_not_actual_motor_response=true, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
