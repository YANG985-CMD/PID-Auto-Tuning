function report=auditMotorFeasibleFactualForecast(input,study,speedModel,currentModel,replaySummary,output)
% Frozen one-decision forecasts; neither policy returns nor measured performance.
arguments
    input (1,1) string
    study (1,1) string
    speedModel (1,1) string
    currentModel (1,1) string
    replaySummary (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);c=s.fullHallContract;rows=s.fullHallValidation;
assert(s.fullHallAudit.passed && isequal(c.action_mask,[1 0]));
speed=jsondecode(fileread(speedModel));current=jsondecode(fileread(currentModel));
for model={speed,current}
    m=model{1};assert(m.passed && string(m.input_sha256)==motorFileSHA256(input));
    assert(m.models(2).model=="state-plus-executed-action" && ~m.validation_used_for_selection);
    assert(m.not_a_deployment_selector && m.actual_action_only);
end
assert(speed.diagnostic_response_component=="raw-Hall-speed-MSE");
assert(current.diagnostic_response_component=="nominal-peak-current-square");
parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
parts=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);actual=single(cat(2,parts{:}));
raw=(double(x).*c.state_scale(:)+c.state_center(:)).*c.critic_input_mask(:);
[components,proof]=motorFactualResponseComponents([s.fullHallTrain;rows],c,replaySummary);
components=components(:,numel(s.fullHallTrain)+1:end);
actualSpeed=forecast(speed.models(2),raw,actual);actualCurrent=forecast(current.models(2),raw,actual);
speedParity=abs(sqrt(mean((actualSpeed-components(1,:)).^2))-speed.models(2).heldout_factual_cost_RMSE);
currentParity=abs(sqrt(mean((actualCurrent-components(2,:)).^2))-current.models(2).heldout_factual_cost_RMSE);
assert(speedParity<1e-10 && currentParity<1e-10,'MotorTD3:FactualForecastCoordinates','Recorded-action predictions must reproduce audited factual residuals');
summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
assert(numel(summary.candidates)==3 && motorFileSHA256(input)==string(summary.audited_input_sha256));
boots=string(cellfun(@(r)r.boot_id,rows,UniformOutput=false));w=zeros(1,numel(rows));
for boot=unique(boots(:))',at=boots==boot;w(at)=1/(numel(unique(boots))*sum(at));end
results=struct([]);bestGrid=[];
for candidate=summary.candidates(:)'
    path=fullfile(study,"candidate-complete-Hall-seed-"+candidate.seed+".mat");
    assert(motorFileSHA256(path)==string(candidate.checkpoint_sha256));p=load(path,'trainingState','contract');
    assert(isequal(p.contract.state_center,c.state_center) && isequal(p.contract.state_scale,c.state_scale));
    mapped=motorTD3ExecutedAction(predict(p.trainingState.actor,dlarray(x,'CB')),x,p.contract);
    action=single(extractdata(mapped));assert(all(action(2,:)==0));
    base=single(motorBidirectionalContinuousActionFromObservation(zeros(2,numel(rows)),x,p.contract));
    predictedSpeed=forecast(speed.models(2),raw,action);baselineSpeed=forecast(speed.models(2),raw,base);
    predictedCurrent=forecast(current.models(2),raw,action);baselineCurrent=forecast(current.models(2),raw,base);
    if isempty(bestGrid)
        levels=unique(cellfun(@(r)r.action_normalized(1),s.fullHallTrain));
        source=cellfun(@(r)r.actual_source_kp,rows)';grid=inf(numel(levels),numel(rows));
        for k=1:numel(levels)
            a=single([repmat(levels(k),1,numel(rows));zeros(1,numel(rows))]);
            gain=c.encoded_baseline_gains(1)+c.gain_step_scale(1)*levels(k);
            feasible=abs(source-gain)<=.00013556+1e-9;
            predicted=forecast(speed.models(2),raw,a);
            grid(k,feasible)=predicted(feasible);
        end
        bestGrid=min(grid,[],1);assert(all(isfinite(bestGrid)));
        envelope=struct(actual_supported_grid_levels=levels,rate_limit_retained=true, ...
            negative_grid_predictions=sum(bestGrid<0),one_decision_model_room_percent=NaN, ...
            current_constraint_not_applied_to_optimistic_envelope=true, ...
            envelope_is_not_a_true_motor_performance_bound=true,grid_controller_created=false);
        if all(bestGrid>=0) && all(baselineSpeed>0)
            envelope.one_decision_model_room_percent=100*(1-sqrt(sum(w.*bestGrid)/sum(w.*baselineSpeed)));
        end
    end
    invalid=predictedSpeed<0 | baselineSpeed<0 | predictedCurrent<0 | baselineCurrent<0;
    speedChange=NaN;currentChange=NaN;
    if ~any(invalid)
        speedChange=100*(1-sqrt(sum(w.*predictedSpeed)/sum(w.*baselineSpeed)));
        currentChange=sum(w.*sqrt(predictedCurrent*4/.3))-sum(w.*sqrt(baselineCurrent*4/.3));
    end
    value=struct(seed=candidate.seed,checkpoint_sha256=string(candidate.checkpoint_sha256), ...
        validation_states=numel(rows),negative_forecast_states=sum(invalid),negative_predictions_not_clipped=true, ...
        one_decision_predicted_speed_RMSE_improvement_percent=speedChange, ...
        one_decision_predicted_mean_peak_nominal_current_change_A=currentChange, ...
        equal_validation_boot_mass=true,comparison_baseline_move_is_rate_clamped=true, ...
        comparison_is_not_fixed_PI_controller_performance=true, ...
        model_uncertainty_calibrated=false,actual_Actor_motor_responses=0, ...
        candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
    if isempty(results),results=value;else,results(end+1)=value;end %#ok<AGROW>
end
report=struct(passed=true,results=results,recorded_action_speed_prediction_RMSE_parity_error=speedParity, ...
    recorded_action_current_prediction_RMSE_parity_error=currentParity,component_proof=proof, ...
    speed_model_sha256=motorFileSHA256(speedModel),current_model_sha256=motorFileSHA256(currentModel), ...
    input_sha256=motorFileSHA256(input), ...
    forecaster_source_sha256=motorFileSHA256(string(mfilename('fullpath'))+".m"), ...
    optimistic_reachable_grid_envelope=envelope,observed_state_one_decision_forecasts=true, ...
    forecasts_are_not_closed_loop_returns_or_motor_performance=true, ...
    training_performed=false,hardware_accessed=false,Actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
function y=forecast(model,x,a)
features=double(motorLocalQuadraticFeatures(single(x),single(a)))';
assert(size(features,2)==numel(model.feature_center));
design=[(features-model.feature_center(:)')./model.feature_scale(:)' ones(size(features,1),1)];
y=(design*model.coefficients(:))';assert(all(isfinite(y)));
end
