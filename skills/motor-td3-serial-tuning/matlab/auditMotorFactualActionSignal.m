function report=auditMotorFactualActionSignal(input,output,options)
% Train-only boot CV: does actual action improve factual response-cost fit?
% Prediction accuracy cannot establish a counterfactual policy improvement.
arguments
    input (1,1) string
    output (1,1) string
    options.ActionCoordinate (1,1) string {mustBeMember(options.ActionCoordinate,["absolute-target","relative-to-actual"])}="absolute-target"
    options.ResponseComponent (1,1) string {mustBeMember(options.ResponseComponent,["combined","raw-Hall-speed-MSE","nominal-peak-current-square"])}="combined"
    options.ReplaySummary (1,1) string=""
    options.MinimumSourceElapsedMs (1,1) double {mustBeMember(options.MinimumSourceElapsedMs,[0 10000])}=0
    options.CausalHallFeatureFile (1,1) string=""
end
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
c=s.fullHallContract;train=s.fullHallTrain;valid=s.fullHallValidation;
originalTrainWindows=numel(train);originalValidationWindows=numel(valid);
y=cost(train,c);vy=cost(valid,c);
componentProof=struct();
if options.ResponseComponent~="combined" || options.MinimumSourceElapsedMs>0
    assert(strlength(options.ReplaySummary)>0);
    [parts,componentProof,elapsed]=motorFactualResponseComponents([train;valid],c,options.ReplaySummary);
    if options.ResponseComponent~="combined"
        if options.ResponseComponent=="raw-Hall-speed-MSE",component=1;else,component=2;end
        y=parts(component,1:numel(train))';vy=parts(component,numel(train)+1:end)';
    end
    if options.MinimumSourceElapsedMs>0
        selected=elapsed>=options.MinimumSourceElapsedMs;
        tm=selected(1:originalTrainWindows);vm=selected(originalTrainWindows+1:end);
        train=train(tm);valid=valid(vm);y=y(tm);vy=vy(vm);
        assert(~isempty(train) && ~isempty(valid));
    end
end
x=rawState(train,c);vx=rawState(valid,c);
causalHallProof=struct(enabled=false);
if strlength(options.CausalHallFeatureFile)>0
    assert(strlength(options.ReplaySummary)>0 && options.MinimumSourceElapsedMs==0);
    phase=jsondecode(fileread(options.CausalHallFeatureFile));
    assert(phase.passed && string(phase.profile)=="host-confirmed-causal-Hall-sector-age-rpm-v1");
    assert(string(phase.audited_input_sha256)==motorFileSHA256(input));
    assert(string(phase.replay_summary_sha256)==motorFileSHA256(options.ReplaySummary));
    assert(~phase.future_Hall_records_used && ~phase.unconfirmed_past_Hall_records_used && ~phase.Actor_input_contract_changed);
    assert(numel(phase.rows)==numel(train)+numel(valid));
    keys=string({phase.rows.physical_key});assert(numel(unique(keys))==numel(keys));
    extra=zeros(8,numel(train)+numel(valid));allRows=[train;valid];
    for k=1:numel(allRows)
        r=allRows{k};index=find(keys==string(r.physical_key));assert(isscalar(index));p=phase.rows(index);
        assert(string(p.boot_id)==r.boot_id && p.source_Hall_record.t_us<=p.source_t_us);
        assert(p.Hall_age_us==p.source_t_us-p.source_Hall_record.t_us);
        assert(p.source_Hall_record.edge<=p.confirmed_published_count);
        expected=[double((1:6)==p.source_Hall_record.hall_code) p.Hall_age_us/20000 p.source_Hall_record.rpm/1000];
        assert(isequal(expected,p.features(:)'));extra(:,k)=expected(:);
    end
    x=[x;extra(:,1:numel(train))];vx=[vx;extra(:,numel(train)+1:end)];
    causalHallProof=struct(enabled=true,feature_file_sha256=motorFileSHA256(options.CausalHallFeatureFile), ...
        confirmed_host_availability_required=true,causal_feature_names=string(phase.feature_names), ...
        unique_original_windows=numel(allRows),Actor_contract_changed=false,raw_reward_changed=false);
end
a=matrix(train,'action_normalized');va=matrix(valid,'action_normalized');
boot=string(cellfun(@(r)r.boot_id,train,UniformOutput=false));vboot=string(cellfun(@(r)r.boot_id,valid,UniformOutput=false));
assert(isempty(intersect(unique(boot),unique(vboot))));
features={double([x;x.^2])',double(motorLocalQuadraticFeatures(single(x),single(a)))'};
vfeatures={double([vx;vx.^2])',double(motorLocalQuadraticFeatures(single(vx),single(va)))'};
sourceGainAffine=[.003389/c.gain_step_scale(1),-c.encoded_baseline_gains(1)/c.gain_step_scale(1)];
if options.ActionCoordinate=="relative-to-actual"
    features{2}=double(motorGainDeltaQuadraticFeatures(single(x),single(a),sourceGainAffine))';
    vfeatures{2}=double(motorGainDeltaQuadraticFeatures(single(vx),single(va),sourceGainAffine))';
end
names=["state-only","state-plus-executed-action"];penalties=[.001 .01 .1 1 10];
models=struct([]);predictions=zeros(numel(valid),2);folds=unique(boot);
for m=1:2
    D=features{m};cv=zeros(numel(folds),numel(penalties));
    for k=1:numel(folds)
        mask=boot~=folds(k);
        for p=1:numel(penalties)
            fit=ridge(D(mask,:),y(mask),boot(mask),penalties(p));
            z=predictFit(fit,D(~mask,:));cv(k,p)=sqrt(mean((z-y(~mask)).^2));
        end
    end
    [~,choice]=min(mean(cv,1));fit=ridge(D,y,boot,penalties(choice));
    predictions(:,m)=predictFit(fit,vfeatures{m});
    row=struct(model=names(m),feature_count=size(D,2),ridge_penalty=penalties(choice), ...
        train_only_leave_one_boot_out_CV_RMSE=cv, ...
        average_train_only_CV_RMSE=mean(cv(:,choice)), ...
        heldout_factual_cost_RMSE=sqrt(mean((predictions(:,m)-vy).^2)), ...
        heldout_factual_cost_MAE=mean(abs(predictions(:,m)-vy)), ...
        coefficients=fit.beta,feature_center=fit.center,feature_scale=fit.scale, ...
        all_fit_and_penalty_selection_use_training_only=true);
    if isempty(models),models=row;else,models(end+1)=row;end %#ok<AGROW>
end
changed=cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,valid);
byBoot=struct([]);
for b=unique(vboot(:))'
    mask=vboot==b;v=compare(predictions(mask,:),vy(mask));
    v.boot_id=b;v.windows=sum(mask);
    if isempty(byBoot),byBoot=v;else,byBoot(end+1)=v;end %#ok<AGROW>
end
groups=struct(all=compare(predictions,vy),hold=compare(predictions(~changed,:),vy(~changed)), ...
    switching=compare(predictions(changed,:),vy(changed)));
responseTarget="Measured full-Hall/current/overspeed/saturation cost rate";
if options.ResponseComponent~="combined",responseTarget="Measured "+options.ResponseComponent+" cost component";end
report=struct(passed=true,input_sha256=motorFileSHA256(input),models=models,groups=groups, ...
    validation_by_boot=byBoot,training_boots=unique(boot),validation_boots=unique(vboot), ...
    train_windows=numel(train),validation_windows=numel(valid), ...
    original_training_windows=originalTrainWindows,original_validation_windows=originalValidationWindows, ...
    minimum_source_elapsed_ms=options.MinimumSourceElapsedMs,late_selection_does_not_prove_steady_state=true, ...
    factual_response_target=responseTarget, ...
    diagnostic_response_component=options.ResponseComponent,component_proof=componentProof, ...
    causal_Hall_feature_proof=causalHallProof, ...
    training_rewards_and_candidate_criteria_unchanged=true, ...
    known_action_change_penalty_removed_before_fit=true,measured_reward_duration_used=true, ...
    penalty_delta_scale_Kp=.00027112,penalty_scale_is_not_Actor_action_scale=true, ...
    input_standardization_undone_before_fold_fitting=true,normalizer_fit_within_CV_fold=true, ...
    regularization_candidates=penalties,validation_used_for_selection=false, ...
    equal_boot_mass_regression=true, ...
    critic_action_basis=options.ActionCoordinate,source_gain_affine_in_raw_state=sourceGainAffine, ...
    actor_action_and_execution_coordinates_unchanged=true, ...
    relative_basis_changes_feature_class_and_regularization=options.ActionCoordinate=="relative-to-actual", ...
    action_accuracy_gain_is_not_causal_gain_effect=true,actual_action_only=true, ...
    not_a_deployment_selector=true,hardware_accessed=false,TD3_training_performed=false, ...
    actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(struct(passed=true,groups=groups,validation_boots=numel(unique(vboot)))));
end
function x=rawState(rows,c)
x=matrix(rows,'observation');x=(double(x).*c.state_scale(:)+c.state_center(:)).*c.critic_input_mask(:);
end
function x=matrix(rows,name)
parts=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=cat(2,parts{:});
end
function y=cost(rows,c)
y=zeros(numel(rows),1);
for k=1:numel(rows)
    r=rows{k};assert(c.physical_single_step_limit(1)==.00027112);
    delta=(r.actual_target_kp-r.actual_source_kp)/.00027112;
    y(k)=-(r.reward+.0005*delta^2)/(r.measured_reward_span_us/100000);
end
assert(all(isfinite(y)) && all(y>=-1e-10));
end
function fit=ridge(D,y,boots,penalty)
center=mean(D,1);scale=max(std(D,0,1),1e-3);X=[(D-center)./scale ones(size(D,1),1)];
w=zeros(numel(y),1);ids=unique(boots);
for b=ids(:)',mask=boots==b;w(mask)=1/(numel(ids)*sum(mask));end
reg=eye(size(X,2));reg(end,end)=0;
beta=(X'*(w.*X)+penalty*reg)\(X'*(w.*y));
assert(all(isfinite(beta)));fit=struct(beta=beta,center=center,scale=scale);
end
function y=predictFit(fit,D)
y=[(D-fit.center)./fit.scale ones(size(D,1),1)]*fit.beta;
end
function out=compare(p,y)
assert(~isempty(y));rmse=sqrt(mean((p-y).^2,1));
out=struct(windows=numel(y),state_only_RMSE=rmse(1),state_action_RMSE=rmse(2), ...
    factual_prediction_RMSE_change_percent=100*(1-rmse(2)/rmse(1)));
end
