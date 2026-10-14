function report=auditMotorBehaviorFit(input,studies,output)
% Compare imitation convergence with hold-gain and train-only linear references.
% These references do not estimate control performance or authorize hardware.
arguments
    input (1,1) string
    studies (:,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);c=s.fullHallContract;
c.execution_mode="upper8-continuous-step-clamp";c.actor_input_mask(8)=1;
x=matrix(s.fullHallTrain,'observation');a=matrix(s.fullHallTrain,'action_normalized');
vx=matrix(s.fullHallValidation,'observation');va=matrix(s.fullHallValidation,'action_normalized');
spec=motorStreamGainSpec(c.stream_gain_profile);scale=2/(spec.action_upper_limit(1)-spec.action_lower_limit(1));
trainWeight=balanced(a);validWeight=balanced(va);
trainD=[double(x).*c.actor_input_mask(:);ones(1,size(x,2))]';
validD=[double(vx).*c.actor_input_mask(:);ones(1,size(vx,2))]';
penalty=eye(11)*1e-3;penalty(end,end)=0;
beta=(trainD'*(trainWeight(:).*trainD)+penalty)\(trainD'*(trainWeight(:).*double(a(1,:)')));
trainLinear=max(spec.action_lower_limit(1),min(spec.action_upper_limit(1),(trainD*beta)'));
validLinear=max(spec.action_lower_limit(1),min(spec.action_upper_limit(1),(validD*beta)'));
trainLinear=double(motorTD3ExecutedAction([trainLinear;zeros(size(trainLinear))],x,c));
validLinear=double(motorTD3ExecutedAction([validLinear;zeros(size(validLinear))],vx,c));
trainHold=holdAction(x,c);validHold=holdAction(vx,c);
results=struct([]);
for study=studies'
    summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
    assert(motorFileSHA256(input)==string(summary.audited_input_sha256));
    for candidate=summary.candidates(:)'
        path=fullfile(study,"candidate-complete-Hall-seed-"+candidate.seed+".mat");
        assert(motorFileSHA256(path)==string(candidate.checkpoint_sha256));p=load(path,'trainingState','contract');
        trainActions=double(extractdata(motorTD3ExecutedAction(predict(p.trainingState.actor,dlarray(x,'CB')),dlarray(x,'CB'),p.contract)));
        validActions=double(extractdata(motorTD3ExecutedAction(predict(p.trainingState.actor,dlarray(vx,'CB')),dlarray(vx,'CB'),p.contract)));
        row=struct(study=study,seed=candidate.seed,Actor_RL_weight=summary.behavior_cloning_RL_weight, ...
            train_balanced_BC_loss=loss(trainActions,a,trainWeight,scale), ...
            validation_balanced_BC_loss=loss(validActions,va,validWeight,scale), ...
            train_Actor_action_std=std(trainActions(1,:)), ...
            training_recorded_action_std=std(a(1,:)), ...
            train_action_vs_actual_gain_correlation=corr(trainActions(1,:)',trainHold(1,:)'), ...
            Actor_weight_change_l2=candidate.actor_weight_change_l2);
        if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(passed=true,results=results,unique_train_windows=numel(s.fullHallTrain), ...
    unique_validation_windows=numel(s.fullHallValidation), ...
    train_balanced_hold_gain_BC_loss=loss(trainHold,a,trainWeight,scale), ...
    validation_balanced_hold_gain_BC_loss=loss(validHold,va,validWeight,scale), ...
    train_balanced_linear_BC_loss=loss(trainLinear,a,trainWeight,scale), ...
    validation_balanced_linear_BC_loss=loss(validLinear,va,validWeight,scale), ...
    train_linear_coefficients=beta,linear_regularization=1e-3, ...
    linear_reference_fit_uses_training_only=true,all_actions_executed_through_same_continuous_clamp=true, ...
    hold_gain_reference_is_not_a_new_PID_controller=true,BC_fit_is_not_motor_performance=true, ...
    training_performed=false,weights_changed=false,hardware_accessed=false,actor_applied=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
function y=holdAction(x,c)
actual=.003389*(double(x(8,:))*c.state_scale(8)+c.state_center(8));
u=(actual-c.encoded_baseline_gains(1))/c.gain_step_scale(1);
spec=motorStreamGainSpec(c.stream_gain_profile);u=max(spec.action_lower_limit(1),min(spec.action_upper_limit(1),u));
y=double(motorTD3ExecutedAction([u;zeros(size(u))],x,c));
end
function w=balanced(a)
u=unique(a(1,:));w=zeros(1,size(a,2));
for v=u,ids=a(1,:)==v;w(ids)=1/(numel(u)*sum(ids));end
end
function v=loss(p,a,w,scale)
v=sum(w.*(scale*(double(p(1,:))-double(a(1,:)))).^2)/2;
end
function x=matrix(rows,name)
v=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=single(cat(2,v{:}));
end
