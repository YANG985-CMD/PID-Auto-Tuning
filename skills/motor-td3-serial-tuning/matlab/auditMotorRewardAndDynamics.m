function report=auditMotorRewardAndDynamics(folder,output)
% Factual diagnostics on feedback-generated commands; never a calibrated plant.
arguments
    folder (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);
proof=jsondecode(fileread(fullfile(folder,'summary.json')));assert(proof.passed && ~proof.hardware_accessed);
T=readtable(fullfile(folder,'observations.csv'),TextType="string");
C=readtable(fullfile(folder,'reward-components.csv'),TextType="string");
assert(height(T)==proof.rows && height(C)==proof.unique_reward_windows);
assert(all(isfinite(T{:,vartype('numeric')}),'all') && all(isfinite(C{:,vartype('numeric')}),'all'));
assert(isequal(unique(T.Split),["train";"validation"]));
assert(isempty(intersect(unique(T.Boot(T.Split=="train")),unique(T.Boot(T.Split=="validation")))));
C.TotalRate=C.SpeedCost+C.CurrentCost+C.OverspeedCost+C.SaturationCost;
C.CurrentShare=C.CurrentCost./C.TotalRate;C.SpeedShare=C.SpeedCost./C.TotalRate;
% Compare rate-like costs; action cost is discrete and kept separate.
G=groupsummary(C,["Boot","Split"],"mean",["SpeedCost","CurrentCost","OverspeedCost","SaturationCost","CurrentShare","SpeedShare"]);
H=groupsummary(G,"Split",["mean","median"],["mean_CurrentShare","mean_SpeedShare","mean_SpeedCost","mean_CurrentCost"]);
writetable(G,fullfile(output,'reward-by-boot.csv'));writetable(H,fullfile(output,'reward-by-split.csv'));
D=transitionRows(T);assert(height(D)>1000);
train=D.Split=="train";validate=D.Split=="validation";
% Fit only on frozen training boots. Infer effective sampled response, not J/B.
% State derivative over an observed interval vs sampled command: hidden inner
% loop input and sensor/controller correlations remain; no causal identification.
design=[D.CycleSpeedStart D.IqCommandStart ones(height(D),1)];
y=D.CycleSpeedRate;
trBoots=unique(D.Boot(train));weights=zeros(height(D),1);
for b=trBoots(:)',at=train&D.Boot==b;weights(at)=1/(numel(trBoots)*sum(at));end
fit=design(train,:);mu=mean(fit,1);scale=max(std(fit,0,1),1e-8);mu(3)=0;scale(3)=1;
z=(design-mu)./scale;zw=z(train,:).*sqrt(weights(train));yw=y(train).*sqrt(weights(train));
singular=svd(zw);coefficient=zw\yw;native=coefficient./scale(:);native(3)=coefficient(3)-sum(coefficient(1:2).*mu(1:2)'./scale(1:2)');
predict=y*0+design*native;residual=y-predict;
priorRate=mean(y(train));priorResidual=y-priorRate;
byboot=groupsummary(table(D.Boot,D.Split,residual.^2,priorResidual.^2,VariableNames=["Boot","Split","MSE","PriorMSE"]),["Boot","Split"],"mean",["MSE","PriorMSE"]);
hold=byboot.Split=="validation";
validationRMSE=sqrt(mean(byboot.mean_MSE(hold)));priorRMSE=sqrt(mean(byboot.mean_PriorMSE(hold)));
correlation=corrcoef(design(train,1:2));
rankObserved=rank(zw);condition=singular(1)/singular(end);
nominalPositiveTorqueExpected=native(2)>0;nominalDampingExpected=native(1)<0;
model=struct(model="sampled cycle-speed derivative = a*cycle-speed + b*reconstructed Iq command + c", ...
    coefficients=native',rank=rankObserved,normalized_condition=condition,speed_command_correlation=correlation(1,2), ...
    positive_command_gain=nominalPositiveTorqueExpected,negative_speed_damping=nominalDampingExpected, ...
    validation_rate_RMSE_rpm_per_s=validationRMSE,prior_rate_RMSE_rpm_per_s=priorRMSE, ...
    validation_predictive_error_change_percent=100*(1-validationRMSE/priorRMSE), ...
    torque_or_current_calibration_available=false,controller_generated_feedback_data=true, ...
    between_samples_actual_Iq_not_measured=true,electrical_cycle_speed_is_filtered_diagnostic=true, ...
    mechanical_parameters_identified=false,causal_model_identified=false,rollout_or_training_plant_approved=false);
writetable(D,fullfile(output,'sampled-effective-transitions.csv'));writetable(byboot,fullfile(output,'dynamics-by-boot.csv'));
report=struct(passed=true,observations=height(T),reward_windows=height(C),physical_boots=proof.boots, ...
    reward_rate_shares_by_split=table2struct(H),reward_weights_changed=false, ...
    model=model,observation_csv_sha256=motorFileSHA256(fullfile(folder,'observations.csv')), ...
    component_csv_sha256=motorFileSHA256(fullfile(folder,'reward-components.csv')), ...
    training_data_and_primary_raw_Hall_metric_unchanged=true, ...
    physical_motor_trials=0,TD3_updates=0,hardware_accessed=false,Actor_applied=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'summary.json'),'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function D=transitionRows(T)
% Real adjacent telemetry; exclude changes in target reference and >25ms gaps.
ok=T.Boot(1:end-1)==T.Boot(2:end) & T.Seq(2:end)==T.Seq(1:end-1)+1 & ...
    T.ReferenceRpm(1:end-1)==T.ReferenceRpm(2:end) & T.DtUs(2:end)>=15000 & T.DtUs(2:end)<=25000;
a=find(ok);b=a+1;dt=(T.TimeUs(b)-T.TimeUs(a))/1e6;
D=table(T.Boot(a),T.Split(a),T.TimeUs(a),dt,T.CycleSpeedRpm(a),T.IqCommandA(a), ...
    (T.CycleSpeedRpm(b)-T.CycleSpeedRpm(a))./dt,VariableNames=["Boot","Split","TimeUs","DtS","CycleSpeedStart","IqCommandStart","CycleSpeedRate"]);
end
