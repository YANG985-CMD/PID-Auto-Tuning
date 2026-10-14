function report=auditMotorCriticFit(input,study,output)
% Frozen-target diagnostic: distinguish fit error from unsupported action claims.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
assert(s.fullHallAudit.passed && motorFileSHA256(input)==string(summary.audited_input_sha256));
x=matrix(s.fullHallTrain,'observation');nx=matrix(s.fullHallTrain,'next_observation');
a=matrix(s.fullHallTrain,'action_normalized');vx=matrix(s.fullHallValidation,'observation');
vnx=matrix(s.fullHallValidation,'next_observation');va=matrix(s.fullHallValidation,'action_normalized');
duration=cellfun(@(r)r.duration_us,s.fullHallTrain)';vduration=cellfun(@(r)r.duration_us,s.fullHallValidation)';
reward=cellfun(@(r)r.reward,s.fullHallTrain)';vreward=cellfun(@(r)r.reward,s.fullHallValidation)';
rows=struct([]);
for c=summary.candidates(:)'
    path=fullfile(study,"candidate-complete-Hall-seed-"+c.seed+".mat");
    assert(motorFileSHA256(path)==string(c.checkpoint_sha256));checkpoint=load(path,'trainingState','contract');
    contract=checkpoint.contract;t=checkpoint.trainingState;
    C=contract.q_value_shift;
    tr=reward+C*(1-.99.^(duration/100000));vr=vreward+C*(1-.99.^(vduration/100000));
    y=target(t,nx,tr,duration);vy=target(t,vnx,vr,vduration);
    actual=[predictQ(t.critic1,x,a);predictQ(t.critic2,x,a)];
    valid=[predictQ(t.critic1,vx,va);predictQ(t.critic2,vx,va)];
    mask=double(contract.critic_input_mask(:));px=features(double(x).*mask,double(a(1,:)));
    pvx=features(double(vx).*mask,double(va(1,:)));
    % Fixed TRAIN-only standardization and ridge penalty, no validation sweep.
    center=mean(px,1);scale=max(std(px,0,1),1e-6);center(1)=0;scale(1)=1;
    z=(px-center)./scale;vz=(pvx-center)./scale;
    penalty=eye(size(z,2));penalty(1,1)=0;
    beta=(z'*z+size(z,1)*.01*penalty)\(z'*double(y(:)));
    linearTrain=z*beta;linearValidation=vz*beta;
    row=struct(seed=c.seed,train_target_std=std(y),validation_target_std=std(vy), ...
        train_network_residual_rmse=sqrt(mean((actual-y).^2,2))', ...
        validation_network_residual_rmse=sqrt(mean((valid-vy).^2,2))', ...
        validation_network_residual_bias=mean(valid-vy,2)', ...
        train_fixed_polynomial_residual_rmse=sqrt(mean((linearTrain-double(y(:))).^2)), ...
        validation_fixed_polynomial_residual_rmse=sqrt(mean((linearValidation-double(vy(:))).^2)), ...
        train_constant_residual_rmse=std(y,1), ...
        validation_train_constant_residual_rmse=sqrt(mean((double(vy)-mean(double(y))).^2)), ...
        fitted_parameters=numel(beta),ridge_coefficient=.01, ...
        target_from_frozen_TD3_not_actual_return=true,checkpoint_sha256=c.checkpoint_sha256);
    if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
    disp(jsonencode(row));
end
report=struct(passed=true,results=rows,source_input_sha256=motorFileSHA256(input), ...
    fixed_targets_only=true,TD3_weights_changed=false,normalization_fit_training_only=true, ...
    polynomial_is_diagnostic_not_actor_or_measured_effect=true, ...
    hardware_accessed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
end

function values=matrix(rows,name)
parts=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);values=single(cat(2,parts{:}));
end
function q=predictQ(net,x,a)
q=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
end
function y=target(t,x,r,dt)
a=extractdata(predict(t.targetActor,dlarray(x,'CB')));a(2,:)=0;
y=double(motorElapsedTD3Target(single(r),single(predictQ(t.targetCritic1,x,a)), ...
    single(predictQ(t.targetCritic2,x,a)),dt,zeros(size(dt))));
end
function phi=features(x,a)
% Smooth local action dependence, unconstrained sign; neither a plant model
% nor an assumed concave motor response. Current observed Kp remains a state.
phi=[ones(1,size(x,2));x;x.^2;a;a.^2;x.*a;x.*a.^2]';
end
