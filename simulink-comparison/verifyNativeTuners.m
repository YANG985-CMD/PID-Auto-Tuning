function report = verifyNativeTuners(output,checkpoint)
% Compare native operator graphs to golden functions and the actual RL Actor.
root=fileparts(mfilename('fullpath')); addpath(root); ccmp_init(); clear ccmp_assets
if nargin<1,output=root;end
if nargin<2,checkpoint=fullfile(root,'td3_frozen_experimental_checkpoint.mat');end
in=Simulink.SimulationInput('MotorTunerComparison');
in=in.setVariable('ccmpMethod',4).setModelParameter('StopTime','1');out=sim(in);
u=double(out.logsout.get('observations').Values.Data);
x=double(out.logsout.get('td3_normalized_state').Values.Data);
tanhAction=double(out.logsout.get('td3_tanh').Values.Data);
names={'ai_gains','fuzzy_gains','neural_gains','td3_gains'};
golden={@ccmp_ai,@ccmp_fuzzy,@ccmp_neural,@ccmp_td3};errors=zeros(1,4);
for method=1:4
    actual=double(out.logsout.get(names{method}).Values.Data); expected=zeros(size(actual));
    for n=1:size(u,1), expected(n,:)=golden{method}(u(n,:)')';end
    errors(method)=max(abs(actual-expected),[],'all');
end
frozen=load(checkpoint,'experimentalAgent','contract'); actor=getActor(frozen.experimentalAgent);
contract=frozen.contract; expectedAction=zeros(size(tanhAction));
for n=1:size(x,1)
    a=getAction(actor,{single(x(n,:)')}); expectedAction(n,:)=double(a{1}(:))';
end
nativeAction=(tanhAction.*contract.actor_output_affine_scale(:)'+contract.actor_output_affine_bias(:)').*contract.action_mask(:)';
report=struct('native_vs_golden_gain_max_abs_error',errors, ...
    'native_vs_actual_frozen_MATLAB_Actor_action_max_abs_error',max(abs(nativeAction-expectedAction),[],'all'), ...
    'checkpoint',checkpoint,'checkpoint_sha256',ccmp_sha256(checkpoint), ...
    'observation_profile',contract.observation_profile,'feature9','Error two telemetry packets earlier, 40ms', ...
    'samples_compared',size(x,1),'integral_feature','Algebraic proxy iqRef-Kp*error; distribution shift explicitly retained', ...
    'hardware_accessed',false,'deployment_allowed',false,'performance_claim_allowed',false);
assert(all(errors<1e-10));assert(report.native_vs_actual_frozen_MATLAB_Actor_action_max_abs_error<2e-6);
fid=fopen(fullfile(output,'native_tuner_numerical_check.json'),'w');fwrite(fid,jsonencode(report,PrettyPrint=true));fclose(fid);
disp(report);
end
