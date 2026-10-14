function report=trainMotorBidirectionalTD3(auditedInput,replay,output,steps,options)
% Controlled reward ablation on audited physical windows; no device access.
arguments
    auditedInput (1,1) string
    replay (1,1) string
    output (1,1) string
    steps (1,1) double {mustBeInteger,mustBePositive}=600
    options.Sampling (1,1) string {mustBeMember(options.Sampling,["uniform","balanced-actual-actions","balanced-actions-switch-cap4"])}="balanced-actions-switch-cap4"
    options.RewardModes (1,:) string {mustBeMember(options.RewardModes,["legacy-sparse","complete-Hall"])}= "complete-Hall"
    options.Initialization (1,1) string {mustBeMember(options.Initialization,["range-midpoint","near-baseline"])}="range-midpoint"
    options.ActorGainFeature (1,1) string {mustBeMember(options.ActorGainFeature,["observed","masked"])}="observed"
    options.RequireMeasuredSwitches (1,1) logical=true
    options.ValueCentering (1,1) logical=false
    options.CriticArchitecture (1,1) string {mustBeMember(options.CriticArchitecture,["concat-mlp","local-quadratic"])}="concat-mlp"
    options.CriticWeightDecay (1,1) double {mustBeNonnegative,mustBeFinite}=0
    options.TrainingSeedMode (1,1) string {mustBeMember(options.TrainingSeedMode,["legacy-stream","isolated-update-stream"])}="legacy-stream"
    options.CriticLearningRate (1,1) double {mustBePositive,mustBeFinite}=.001
    options.CriticInitialization (1,1) string {mustBeMember(options.CriticInitialization,["random-prior","factual-ridge-bootstrap"])}="random-prior"
    options.ActorLambdaCoordinates (1,1) string {mustBeMember(options.ActorLambdaCoordinates,["native","unshifted-physical"])}="unshifted-physical"
    options.ExecutionMode (1,1) string {mustBeMember(options.ExecutionMode,["bidirectional-continuous-step-clamp"])}="bidirectional-continuous-step-clamp"
    options.ActorRLWeight (1,1) double {mustBeNonnegative,mustBeFinite}=25
    options.ActorLearningRate (1,1) double {mustBePositive,mustBeFinite}=.0001
    options.TargetNoiseSource (1,1) string {mustBeMember(options.TargetNoiseSource,["shared-update-stream","separate-stream"])}="shared-update-stream"
end
assert(steps<=1200 && mod(steps,2)==0 && ~isfolder(output));mkdir(output);
s=load(auditedInput);assert(s.fullHallAudit.passed && ~s.fullHallAudit.training_performed);
contract=s.fullHallContract;train=s.fullHallTrain;validation=s.fullHallValidation;
assert(string(contract.stream_gain_profile)=="bidirectional16-upper8-fullhall");
assert(options.RequireMeasuredSwitches && options.Sampling=="balanced-actions-switch-cap4" && options.ActorGainFeature=="observed");
assert(options.ExecutionMode=="bidirectional-continuous-step-clamp");

if options.CriticInitialization=="factual-ridge-bootstrap"
    assert(options.CriticArchitecture=="local-quadratic" && options.CriticWeightDecay>0, ...
        'MotorTD3:RidgeInitialization','Factual initialization needs the positive-penalty local quadratic Critic');
end
rewardProfile="post-ACK-complete-Hall-v1";originalPhysicalUnchanged=true;
if isfield(contract,'learning_reward_profile')
    rewardProfile=string(contract.learning_reward_profile);
    assert(rewardProfile=="full-decision-observed-latency-v1" && contract.raw_recorded_rewards_unchanged && contract.post_ack_reward_retained);
    assert(isequal(options.RewardModes,"complete-Hall"),'MotorTD3:RewardProfile','Full interval input requires explicit complete-Hall mode');
    originalPhysicalUnchanged=false;
end
% The audit inherits a parent policy contract; its old critic bias was never
% used by this trainer. Record the actual reward-specific value instead.
if isfield(contract,'critic_initial_value'),contract=rmfield(contract,'critic_initial_value');end
contract.critic_initial_value_source="Per-reward candidate initialization, recorded in candidateReport";
assert(numel(train)>=128 && numel(validation)>=128 && isequal(contract.action_mask,[1 0]));
switchTrain=0;switchValidation=0;switchMetadataAvailable=all(cellfun(@(r)isfield(r,'actual_source_kp') && isfield(r,'actual_target_kp'),[train;validation]));
if switchMetadataAvailable
    switchTrain=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,train));
    switchValidation=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,validation));
end
if options.RequireMeasuredSwitches
    assert(switchMetadataAvailable && switchTrain>=32 && switchValidation>=32, ...
        'MotorTD3:SwitchSupport','Dynamic gain learning requires a minibatch of measured switches in both boot splits');
    for row=[train;validation]'
        r=row{1};sourceFromObservation=.003389*(r.observation(8)*contract.state_scale(8)+contract.state_center(8));
        targetFromAction=contract.encoded_baseline_gains(1)+contract.gain_step_scale(1)*r.action_normalized(1);
        assert(abs(sourceFromObservation-r.actual_source_kp)<1e-9 && abs(targetFromAction-r.actual_target_kp)<1e-9, ...
            'MotorTD3:SwitchSupport','Switch metadata must agree with audited actual state/action');
    end
end
if options.ActorGainFeature=="masked"
    assert(string(contract.feature_names(8))=="actual_kp");
    contract.actor_input_mask(8)=0;contract.actor_actual_kp_input_masked=true;
else
    assert(string(contract.feature_names(8))=="actual_kp");
    contract.actor_input_mask(8)=1;contract.actor_actual_kp_input_masked=false;
end
contract.execution_mode=options.ExecutionMode;
if options.ExecutionMode=="upper8-exact-grid-straight-through"
    assert(string(contract.stream_gain_profile)=="upper8-fullhall" && options.ActorGainFeature=="observed");
    contract.execution_mapping_version="upper8-exact-readback-nearest-feasible-hold-ties-v1";
    contract.host_single_kp_step_limit=.00013556;
    contract.execution_wrapper_required=true;
    contract.straight_through_gradient_is_experimental_surrogate=true;
end
if options.ExecutionMode=="bidirectional-continuous-step-clamp"
    assert(string(contract.stream_gain_profile)=="bidirectional16-upper8-fullhall" && options.ActorGainFeature=="observed");
    contract.execution_mapping_version="bidirectional16-upper8-continuous-relative-step-clamp-v1";
    contract.host_single_kp_step_limit=.00013556;
    contract.execution_wrapper_required=true;
    contract.straight_through_gradient_is_experimental_surrogate=false;
end
spec=motorStreamGainSpec(contract.stream_gain_profile);actorMask=contract.actor_input_mask(:);
criticMask=contract.critic_input_mask(:);
assert(all(ismember(actorMask,[0 1])) && all(ismember(criticMask,[0 1])));
assert(criticMask(8)==1,'MotorTD3:CriticState','Critic must retain observed actual gain');
x=matrix(train,'observation');nx=matrix(train,'next_observation');a=matrix(train,'action_normalized');
duration=cellfun(@(r)r.duration_us,train)';vx=matrix(validation,'observation');
vnx=matrix(validation,'next_observation');va=matrix(validation,'action_normalized');
vduration=cellfun(@(r)r.duration_us,validation)';
switchSampler=[];samplingSupport=struct(mode=options.Sampling);
switchFlags=false(1,numel(train));
if switchMetadataAvailable,switchFlags=cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,train)';end
if options.Sampling=="balanced-actions-switch-cap4"
    assert(options.RequireMeasuredSwitches && contract.stream_gain_profile=="bidirectional16-upper8-fullhall");
    switchSampler=prepareMotorBidirectionalSwitchSampler(a,cellfun(@(r)r.actual_source_kp,train), ...
        cellfun(@(r)r.actual_target_kp,train),string(cellfun(@(r)r.boot_id,train,UniformOutput=false)));
    samplingSupport=switchSampler.report;
end
if options.ExecutionMode~="continuous-experimental"
    for recorded={struct(x=x,a=a),struct(x=vx,a=va)}
        p=recorded{1};mapped=motorTD3ExecutedAction(p.a,p.x,contract);
        assert(max(abs(double(mapped(:)-p.a(:))))<1e-6, ...
            'MotorTD3:ExecutionReplay','Recorded actions must obey the same execution mapping');
    end
end
criticFeatureCenter=zeros(42,1);criticFeatureScale=ones(42,1);
if options.CriticArchitecture=="local-quadratic"
    features=double(motorLocalQuadraticFeatures(x.*single(criticMask),a));
    criticFeatureCenter=mean(features,2);criticFeatureScale=max(std(features,0,2),1e-3);
end
contract.critic_architecture=options.CriticArchitecture;
contract.critic_feature_center=criticFeatureCenter;contract.critic_feature_scale=criticFeatureScale;
contract.critic_feature_normalizer_fit_split="training boots only";
report=struct(source="Audited real motor complete-Hall reward TD3 experiment", ...
    seeds=[7 17 27],reward_modes=options.RewardModes,steps_per_candidate=steps, ...
    unique_train_windows=numel(train),unique_validation_windows=numel(validation), ...
    training_boot_id=contract.training_boot_id,validation_boot_id=contract.validation_boot_id, ...
    training_boot_ids=contract.training_boot_ids,validation_boot_ids=contract.validation_boot_ids, ...
    replay_manifest_sha256=motorFileSHA256(fullfile(replay,'summary.json')), ...
    audited_input_sha256=motorFileSHA256(auditedInput),learning_contract=contract, ...
    trainer_source_sha256=motorFileSHA256(string(mfilename('fullpath'))+".m"), ...
    actor_constructor_source_sha256=motorFileSHA256(which('createMotorTD3')), ...
    quadratic_critic_source_sha256=motorFileSHA256(which('createMotorLocalQuadraticCritic')), ...
    quadratic_features_source_sha256=motorFileSHA256(which('motorLocalQuadraticFeatures')), ...
    elapsed_target_source_sha256=motorFileSHA256(which('motorElapsedTD3Target')), ...
    backend="dlnetwork+dlgradient+adamupdate",native_trainFromData_called=false, ...
    batch_size=32,delayed_policy_period=2,discount_rule="0.99^(measured duration/100000us)", ...
    actor_learning_rate=options.ActorLearningRate,critic_learning_rate=options.CriticLearningRate,target_tau=.005, ...
    target_noise_std=.05,target_noise_clip=.1,target_noise_source=options.TargetNoiseSource, ...
    separate_target_noise_seed_offset=200000,behavior_cloning_RL_weight=options.ActorRLWeight, ...
    critic_architecture=options.CriticArchitecture,critic_weight_decay=options.CriticWeightDecay, ...
    critic_initialization=options.CriticInitialization, ...
    factual_ridge_initializer_source_sha256=motorFileSHA256(which('initializeMotorFactualRidgeCritics')), ...
    actor_lambda_value_coordinates=options.ActorLambdaCoordinates, ...
    actor_loss_source_sha256=motorFileSHA256(which('motorTD3ActorLoss')), ...
    execution_mode=options.ExecutionMode,execution_wrapper_source_sha256=motorFileSHA256(which('motorUpper8ActionFromObservation')), ...
    continuous_execution_wrapper_source_sha256=motorFileSHA256(which('motorBidirectionalContinuousActionFromObservation')), ...
    execution_dispatch_source_sha256=motorFileSHA256(which('motorTD3ExecutedAction')), ...
    training_seed_mode=options.TrainingSeedMode,isolated_update_seed_offset=100000, ...
    actual_action_sampling=options.Sampling,sampling_support=samplingSupport, ...
    actor_initialization=options.Initialization, ...
    actor_actual_gain_feature=options.ActorGainFeature, ...
    measured_switch_support_required=options.RequireMeasuredSwitches, ...
    measured_switch_metadata_available=switchMetadataAvailable, ...
    measured_switch_train_windows=switchTrain,measured_switch_validation_windows=switchValidation, ...
    training_only_value_centering=options.ValueCentering, ...
    learning_reward_profile=rewardProfile,original_physical_rewards_unchanged=originalPhysicalUnchanged, ...
    raw_recorded_rewards_unchanged=true, ...
    old_replay_appended=false,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false,candidates=struct([]));
write(fullfile(output,'study-contract.json'),report);
actualActionLevels=unique(a(1,:));actionGroups=arrayfun(@(v)find(a(1,:)==v),actualActionLevels,UniformOutput=false);
if options.Sampling~="uniform"
    expectedActionGroups=3;if contract.stream_gain_profile=="lower16-upper4-fullhall",expectedActionGroups=4;end
    if contract.stream_gain_profile=="bidirectional16-upper8-fullhall",expectedActionGroups=9;end
    assert(numel(actualActionLevels)==expectedActionGroups && all(cellfun(@numel,actionGroups)>=32), ...
        'MotorTD3:Support','Balanced training requires every declared actually held gain');
end
for mode=report.reward_modes
    field='reward';if mode=="legacy-sparse",field='legacy_time_reward';end
    reward=single(cellfun(@(r)r.(field),train)');vreward=single(cellfun(@(r)r.(field),validation)');
    initialQ=mean(double(reward))/(1-mean(.99.^(duration/100000)));
    valueShift=0;
    if options.ValueCentering
        assert(string(contract.learning_task)=="continuing");
        valueShift=-initialQ;
        reward=single(double(reward)+valueShift*(1-.99.^(duration/100000)));
        vreward=single(double(vreward)+valueShift*(1-.99.^(vduration/100000)));
        initialQ=mean(double(reward))/(1-mean(.99.^(duration/100000)));
    end
    contract.q_value_shift=valueShift;
    contract.critic_initial_value=initialQ;
    contract.learning_reward_transform="r + C*(1-gamma^measured_dt), continuing-task constant value potential";
    contract.original_physical_rewards_unchanged=originalPhysicalUnchanged;
    for seed=report.seeds
        initialAction=NaN(2,1);if options.Initialization=="near-baseline",initialAction=[0;0];end
        initial=createMotorTD3(seed,[1;0],0,ActorInputMask=actorMask,CriticInputMask=criticMask, ...
            CriticInitialValue=initialQ,CriticL2RegularizationFactor=options.CriticWeightDecay, ...
            CriticLearningRate=options.CriticLearningRate, ...
            ActorLearningRate=options.ActorLearningRate, ...
            InitialNormalizedAction=initialAction, ...
            CriticArchitecture=options.CriticArchitecture,CriticFeatureCenter=criticFeatureCenter,CriticFeatureScale=criticFeatureScale, ...
            ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:));
        actor=getModel(getActor(initial));initialActor=actor;critics=getCritic(initial);
        initialZeroAction=double(extractdata(predict(actor,dlarray(zeros(10,1,'single'),'CB'))));
        q1=getModel(critics(1));q2=getModel(critics(2));
        initializationReport=struct(mode="random-prior",ridge_initialization_fits=0,validation_data_used=false);
        if options.CriticInitialization=="factual-ridge-bootstrap"
            assert(all(cellfun(@(r)isfield(r,'boot_id'),train)));
            trainBoots=string(cellfun(@(r)r.boot_id,train,UniformOutput=false));
            gamma=.99.^(duration/100000);
            factualTarget=single(double(reward)+gamma*initialQ);
            [q1,q2,initializationReport]=initializeMotorFactualRidgeCritics(q1,q2,x,a,factualTarget, ...
                trainBoots(:),criticFeatureCenter,criticFeatureScale,criticMask,options.CriticWeightDecay,seed);
        end
        ta=actor;tq1=q1;tq2=q2;
        if options.TrainingSeedMode=="isolated-update-stream",rng(seed+100000,'twister');end
        noiseStream=[];
        if options.TargetNoiseSource=="separate-stream",noiseStream=RandStream('mt19937ar','Seed',seed+200000);end
        noiseDraws=zeros(steps,32,'single');
        av=[];as=[];v1=[];s1=[];v2=[];s2=[];actorSteps=0;losses=zeros(steps,3);sampleCounts=zeros(size(actualActionLevels));
        targetNoiseExecutedChanges=0;targetActionSamples=0;sampledSwitchCount=0;
        scale=single([2/(spec.action_upper_limit(1)-spec.action_lower_limit(1));1]);
        for k=1:steps
            if options.Sampling=="balanced-actual-actions"
                groupIds=randi(numel(actionGroups),1,32);ids=zeros(1,32);
                for sample=1:32,available=actionGroups{groupIds(sample)};ids(sample)=available(randi(numel(available)));end
            elseif options.Sampling=="balanced-actions-switch-cap4"
                ids=sampleMotorSwitchIndices(switchSampler,32);
            else
                ids=randi(numel(train),1,32);
            end
            for actionIndex=1:numel(actualActionLevels),sampleCounts(actionIndex)=sampleCounts(actionIndex)+sum(a(1,ids)==actualActionLevels(actionIndex));end
            sampledSwitchCount=sampledSwitchCount+sum(switchFlags(ids));
            bx=dlarray(x(:,ids),'CB');bnx=dlarray(nx(:,ids),'CB');ba=dlarray(a(:,ids),'CB');
            nextAction=single(extractdata(predict(ta,bnx)));beforeNoise=nextAction;
            if isempty(noiseStream),noise=single(randn(1,32)*.05);else,noise=single(randn(noiseStream,1,32)*.05);end
            noiseDraws(k,:)=noise;
            nextAction(1,:)=max(spec.action_lower_limit(1),min(spec.action_upper_limit(1),nextAction(1,:)+max(-.1,min(.1,noise))));
            nextAction(2,:)=0;
            if options.ExecutionMode~="continuous-experimental"
                nextAction=motorTD3ExecutedAction(nextAction,bnx,contract);
                beforeNoise=motorTD3ExecutedAction(beforeNoise,bnx,contract);
                targetNoiseExecutedChanges=targetNoiseExecutedChanges+sum(nextAction(1,:)~=beforeNoise(1,:));
                targetActionSamples=targetActionSamples+size(nextAction,2);
            end
            y=motorElapsedTD3Target(reward(ids),extractdata(predict(tq1,bnx,dlarray(nextAction,'CB'))), ...
                extractdata(predict(tq2,bnx,dlarray(nextAction,'CB'))),duration(ids),zeros(1,32));
            [l1,g1]=dlfeval(@criticLoss,q1,bx,ba,dlarray(y,'CB'),options.CriticWeightDecay);
            [l2,g2]=dlfeval(@criticLoss,q2,bx,ba,dlarray(y,'CB'),options.CriticWeightDecay);
            [q1,v1,s1]=adamupdate(q1,g1,v1,s1,k,options.CriticLearningRate);[q2,v2,s2]=adamupdate(q2,g2,v2,s2,k,options.CriticLearningRate);
            la=NaN;
            if mod(k,2)==0
                [lossA,ga]=dlfeval(@motorTD3ActorLoss,actor,q1,bx,ba,scale,valueShift, ...
                    options.ActorLambdaCoordinates,options.ExecutionMode,contract,options.ActorRLWeight);actorSteps=actorSteps+1;
                [actor,av,as]=adamupdate(actor,ga,av,as,actorSteps,options.ActorLearningRate);la=double(extractdata(lossA));
                ta=blend(ta,actor,.005);tq1=blend(tq1,q1,.005);tq2=blend(tq2,q2,.005);
            end
            losses(k,:)=[double(extractdata(l1)),double(extractdata(l2)),la];
            assert(all(isfinite(losses(k,1:2))));
        end
        assert(numel(sampleCounts)==numel(actualActionLevels) && sum(sampleCounts)==32*steps, ...
            'MotorTD3:SamplingAudit','Every sampled transition must belong to an actual action group');
        actions=double(extractdata(predict(actor,dlarray(vx,'CB'))));requestedActions=actions;assert(all(actions(2,:)==0));
        if options.ExecutionMode~="continuous-experimental"
            actions=double(motorTD3ExecutedAction(actions,vx,contract));
        end
        assert(all(actions(1,:)>=spec.action_lower_limit(1)-1e-6 & actions(1,:)<=spec.action_upper_limit(1)+1e-6));
        nextActions=single(extractdata(predict(ta,dlarray(vnx,'CB'))));
        if options.ExecutionMode~="continuous-experimental"
            nextActions=motorTD3ExecutedAction(nextActions,vnx,contract);
        end
        targets=motorElapsedTD3Target(vreward,extractdata(predict(tq1,dlarray(vnx,'CB'),dlarray(nextActions,'CB'))), ...
            extractdata(predict(tq2,dlarray(vnx,'CB'),dlarray(nextActions,'CB'))),vduration,zeros(1,numel(validation)));
        loggedQ1=double(extractdata(predict(q1,dlarray(vx,'CB'),dlarray(va,'CB'))));
        loggedQ2=double(extractdata(predict(q2,dlarray(vx,'CB'),dlarray(va,'CB'))));
        trainPolicyAction=predict(actor,dlarray(x,'CB'));
        if options.ExecutionMode~="continuous-experimental"
            trainPolicyAction=motorTD3ExecutedAction(trainPolicyAction,x,contract);
        end
        trainPolicyQ=double(extractdata(predict(q1,dlarray(x,'CB'),trainPolicyAction)));
        scaleQ=trainPolicyQ;
        if options.ActorLambdaCoordinates=="unshifted-physical",scaleQ=scaleQ-valueShift;end
        finalTrainLambda=options.ActorRLWeight/max(mean(abs(scaleQ)),1e-6);
        rawKp=contract.encoded_baseline_gains(1)+contract.gain_step_scale(1)*actions(1,:);
        changed=distance(actor,initialActor);assert(changed>0 && all(isfinite(actions),'all'));
        candidateReport=struct(reward_mode=mode,seed=seed,critic_update_iterations=steps,actor_updates=actorSteps, ...
            action_mask=[1 0],actor_weight_change_l2=changed, ...
            critic_architecture=options.CriticArchitecture,critic_weight_decay=options.CriticWeightDecay, ...
            critic_initialization=options.CriticInitialization,critic_initialization_report=initializationReport, ...
            actor_lambda_value_coordinates=options.ActorLambdaCoordinates, ...
            actor_RL_weight=options.ActorRLWeight, ...
            actor_learning_rate=options.ActorLearningRate, ...
            execution_mode=options.ExecutionMode,execution_wrapper_required=options.ExecutionMode~="continuous-experimental", ...
            target_smoothing_executed_action_changes=targetNoiseExecutedChanges,target_action_samples=targetActionSamples, ...
            target_noise_source=options.TargetNoiseSource, ...
            learning_reward_profile=rewardProfile,original_physical_rewards_unchanged=originalPhysicalUnchanged, ...
            critic_learning_rate=options.CriticLearningRate, ...
            actor_input_mask=actorMask,critic_input_mask=criticMask, ...
            initial_zero_state_normalized_action=initialZeroAction, ...
            critic_value_shift_C=valueShift,critic_Q_values_require_subtracting_C=true, ...
            critic_initial_value=initialQ, ...
            learning_reward_transform=contract.learning_reward_transform, ...
            value_shift_fit_split="training boots only", ...
            final_training_policy_mean_abs_native_Q=mean(abs(trainPolicyQ)), ...
            final_training_policy_mean_abs_scaling_Q=mean(abs(scaleQ)), ...
            final_training_actor_lambda=finalTrainLambda, ...
            minibatch_action_levels_normalized=actualActionLevels,minibatch_action_sample_counts=sampleCounts, ...
            sampled_switch_count=sampledSwitchCount,sampled_hold_count=32*steps-sampledSwitchCount, ...
            minibatch_action_sampling_audit_passed=true, ...
            validation_target_residual_rmse=[sqrt(mean((loggedQ1-targets).^2)),sqrt(mean((loggedQ2-targets).^2))], ...
            validation_raw_kp_range=[min(rawKp) max(rawKp)],fixed_ki=.00144, ...
            validation_requested_normalized_Kp_range=[min(requestedActions(1,:)) max(requestedActions(1,:))], ...
            independent_actor_physical_performance_verified=false,candidate_admission=false, ...
            deployment_allowed=false,performance_claim_allowed=false);
        oi=getObservationInfo(initial);ai=getActionInfo(initial);
        policy=rlContinuousDeterministicActor(actor,oi,ai,'ObservationInputNames','state');
        qs=[rlQValueFunction(q1,oi,ai,'ObservationInputNames','state','ActionInputNames','action'), ...
            rlQValueFunction(q2,oi,ai,'ObservationInputNames','state','ActionInputNames','action')];
        experimentalAgent=rlTD3Agent(policy,qs,initial.AgentOptions);experimentalAgent.UseExplorationPolicy=false;
        trainingState=struct(actor=actor,critic1=q1,critic2=q2,targetActor=ta,targetCritic1=tq1,targetCritic2=tq2, ...
            actor_average=av,actor_square_average=as,critic1_average=v1,critic1_square_average=s1, ...
            critic2_average=v2,critic2_square_average=s2,rng_state=rng,critic_iterations=steps,actor_iterations=actorSteps);
        trainingState.target_smoothing_noise=noiseDraws;
        if ~isempty(noiseStream),trainingState.target_noise_stream_state=noiseStream.State;end
        name="candidate-"+mode+"-seed-"+seed;save(fullfile(output,name+".mat"),'experimentalAgent','contract','candidateReport','trainingState');
        candidateReport.checkpoint_sha256=motorFileSHA256(fullfile(output,name+".mat"));
        exportMotorTD3DiagnosticJSON(fullfile(output,name+".mat"),fullfile(output,name+"-networks.json"));
        prediction=table((1:numel(validation))',actions(1,:)',rawKp',(loggedQ1-valueShift)',(loggedQ2-valueShift)',double(targets(:))-valueShift, ...
            'VariableNames',{'heldout_window','action_normalized_Kp','raw_Kp','Q1_actual_action','Q2_actual_action','elapsed_target'});
        writetable(prediction,fullfile(output,name+"-holdout.csv"));writematrix(losses,fullfile(output,name+"-loss.csv"));
        if isempty(report.candidates),report.candidates=candidateReport;else,report.candidates(end+1)=candidateReport;end
        write(fullfile(output,'training-progress.json'),report);
        fprintf('Full-Hall TD3 %s seed%d: %d critic/%d Actor updates complete\n',mode,seed,steps,actorSteps);
    end
end
report.critic_update_iterations=sum([report.candidates.critic_update_iterations]);
report.actor_updates=sum([report.candidates.actor_updates]);
report.reason="No independent frozen Actor physical response; behavior probe did not pass replicated performance gates";
write(fullfile(output,'training-summary.json'),report);
end

function x=matrix(rows,name)
values=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=single(cat(2,values{:}));
end
function [loss,g]=criticLoss(net,x,a,y,decay)
q=forward(net,x,a);loss=mean((q-y).^2,'all');
if decay>0
    for k=1:height(net.Learnables)
        if net.Learnables.Parameter(k)=="Weights",loss=loss+decay*sum(net.Learnables.Value{k}.^2,'all');end
    end
end
g=dlgradient(loss,net.Learnables);
end
function target=blend(target,net,tau)
for k=1:height(target.Learnables),target.Learnables.Value{k}=(1-tau)*target.Learnables.Value{k}+tau*net.Learnables.Value{k};end
end
function value=distance(a,b)
value=0;for k=1:height(a.Learnables),value=value+sum(double(extractdata(a.Learnables.Value{k}-b.Learnables.Value{k})).^2,'all');end;value=sqrt(value);
end
function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
