function report=diagnoseSpeedLoopAsyncCandidate(checkpoint,dataset,outputDir)
% Frozen whole-boot holdout. Critic diagnostics do not qualify motor effects.
arguments
    checkpoint (1,1) string
    dataset (1,1) string
    outputDir (1,1) string
end
assert(~isfolder(outputDir));mkdir(outputDir);
loaded=load(checkpoint,'experimentalAgent','contract','candidateReport');
physical=validateSpeedLoopResponseReplay(dataset,[1;0]);
[learning,c]=prepareMotorCausalReplay(physical,"absolute-target",loaded.contract.state_standardized, ...
    ObservationProfile="history20-40",LearningTask="continuing");
assert(isequal(c.state_center,loaded.contract.state_center) && isequal(c.state_scale,loaded.contract.state_scale));
d=diagnoseMotorTD3Policy(loaded.experimentalAgent,learning.validation);
action=d.predictions{:,{'actor_kp_action','actor_ki_action'}};
gains=action.*c.gain_step_scale+c.encoded_baseline_gains;
lower=0;
if isfield(loaded.contract,'stream_gain_profile')
    spec=motorStreamGainSpec(string(loaded.contract.stream_gain_profile));lower=spec.action_lower_limit(1);
end
assert(all(action(:,1)>=lower-1e-6 & action(:,1)<=.5+1e-6) && all(action(:,2)==0));
assert(all(gains(:,2)==double(single(.00144))));
d.predictions.candidate_kp=gains(:,1);d.predictions.candidate_ki=gains(:,2);
writetable(d.predictions,fullfile(outputDir,'holdout-predictions.csv'));
report=struct(checkpoint_sha256=motorFileSHA256(checkpoint),dataset_sha256=string(physical.summary.dataset_sha256), ...
    validation_windows=numel(learning.validation),holdout_boots=unique(string(d.predictions.boot_id)), ...
    diagnostics=d.metrics,candidate_kp_range=[min(gains(:,1)) max(gains(:,1))],fixed_ki=.00144, ...
    action_mask=[1 0],hardware_accessed=false,physical_candidate_validation_performed=false, ...
    admission_passed=false,deployment_allowed=false,performance_claim_allowed=false, ...
    rejection="No independent physical Actor comparison. Commissioning images accept reviewed discrete gains; continuous Actor outputs are not admitted.");
f=fopen(fullfile(outputDir,'candidate-diagnostics.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
