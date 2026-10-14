function report=testMotorGainDeltaFeatures(input,priorReport,outputFolder)
% Verify source gain coordinates and unchanged default factual diagnostics.
arguments
    input (1,1) string
    priorReport (1,1) string
    outputFolder (1,1) string
end
assert(isfolder(outputFolder));
s=load(input);c=s.fullHallContract;
parts=cellfun(@(r)r.observation(:),s.fullHallTrain,UniformOutput=false);
x=single((double(cat(2,parts{:})).*c.state_scale(:)+c.state_center(:)).*c.critic_input_mask(:));
assert(size(x,1)==10 && c.critic_input_mask(8)==1);
source=cellfun(@(r)r.actual_source_kp,s.fullHallTrain)';
affine=[.003389/c.gain_step_scale(1),-c.encoded_baseline_gains(1)/c.gain_step_scale(1)];
a=single([(source-c.encoded_baseline_gains(1))/c.gain_step_scale(1);zeros(size(source))]);
p=motorGainDeltaQuadraticFeatures(x,a,affine);
holdError=max(abs(p(21:end,:)),[],'all');assert(holdError<1e-6);

z=single(reshape(1:30,10,3)/100);z(8,:)=[.5 1 1.5];
action=single([0 1.25 1.5;0 0 0]);u=single([0 .25 -.5]);
expected=[z;z.^2;u;u.^2;z.*u;z.*u.^2];
actual=motorGainDeltaQuadraticFeatures(z,action,[2 -1]);
assert(isequal(actual,expected));

path=fullfile(outputFolder,'default-factual-parity.json');
auditMotorFactualActionSignal(input,path);
old=jsondecode(fileread(priorReport));now=jsondecode(fileread(path));
assert(isequal(old.groups,now.groups));
err=0;
for k=1:2
    for field=["coefficients","feature_center","feature_scale","train_only_leave_one_boot_out_CV_RMSE"]
        lhs=old.models(k).(field);rhs=now.models(k).(field);
        assert(isequal(size(lhs),size(rhs)));
        err=max(err,max(abs(lhs-rhs),[],'all'));
    end
end
assert(err<1e-12);
report=struct(passed=true,real_training_windows=numel(s.fullHallTrain), ...
    actual_source_gain_hold_action_feature_maximum=holdError, ...
    known_delta_feature_fixture_exact=true,default_group_metrics_exact=true, ...
    default_model_numeric_maximum_difference=err, ...
    input_sha256=motorFileSHA256(input), ...
    prior_report_sha256=motorFileSHA256(priorReport), ...
    TD3_gradient_updates=0,hardware_accessed=false,deployment_allowed=false);
target=fullfile(outputFolder,'action-coordinate-tests.json');assert(~isfile(target));
f=fopen(target,'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
