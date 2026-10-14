function report=trainSpeedLoopCausalTD3(dataset,outputDir,coordinates,standardize,actionMask,options)
% Diagnostic candidates use experimentalAgent, incompatible with live loaders.
arguments
    dataset (1,1) string
    outputDir (1,1) string
    coordinates (1,1) string {mustBeMember(coordinates,["delta","absolute-target"])}
    standardize (1,1) logical
    actionMask (2,1) double = [1;1]
    options.Epochs (1,1) double {mustBeInteger,mustBePositive} = 10
    options.BehaviorCloningWeight (1,1) double {mustBeNonnegative} = .25
    options.InitializeCriticFromTrainingReward (1,1) logical = false
    options.CriticL2RegularizationFactor (1,1) double {mustBeNonnegative} = 1e-4
    options.ActionLowerLimit (2,1) double = -ones(2,1)
    options.ActionUpperLimit (2,1) double = ones(2,1)
    options.ActionChangePenaltyWeight (1,1) double = NaN
    options.ObservationProfile (1,1) string {mustBeMember(options.ObservationProfile,["physical","history20-40"])} = "physical"
    options.LearningTask (1,1) string {mustBeMember(options.LearningTask,["continuing","bounded-trial"])} = "continuing"
    options.ActorInputMask (10,1) double = ones(10,1)
    options.CriticWarmStartSteps (1,1) double {mustBeInteger,mustBeNonnegative} = 0
end
assert(options.Epochs<=100 && isfinite(options.BehaviorCloningWeight) && isfinite(options.CriticL2RegularizationFactor));
physical=validateSpeedLoopResponseReplay(dataset,actionMask);assert(physical.training_ready);
[replay,contract]=prepareMotorCausalReplay(physical,coordinates,standardize, ...
    ObservationProfile=options.ObservationProfile,LearningTask=options.LearningTask);
contract.action_mask=actionMask';
contract.action_lower_limit=options.ActionLowerLimit';
contract.action_upper_limit=options.ActionUpperLimit';
contract.actor_output_affine_scale=((options.ActionUpperLimit-options.ActionLowerLimit)/2)';
contract.actor_output_affine_bias=((options.ActionUpperLimit+options.ActionLowerLimit)/2)';
contract.actor_input_mask=options.ActorInputMask';
contract.critic_warm_start_steps=options.CriticWarmStartSteps;
contract.support_limits_are_not_physical_performance_evidence=true;
assert(isnan(options.ActionChangePenaltyWeight) || ...
    (isfinite(options.ActionChangePenaltyWeight) && options.ActionChangePenaltyWeight>=0 && ...
     options.ActionChangePenaltyWeight<=.005));
contract.action_change_penalty_weight=options.ActionChangePenaltyWeight;
contract.physical_reward_preserved=true;
contract.behavior_cloning_weight_semantics="Positive MathWorks Wbc scales the RL term through Wbc/mean(abs(Q)); increasing it reduces relative imitation; zero disables regularization";
contract.regularizer_documentation="https://www.mathworks.com/help/reinforcement-learning/ref/rl.option.rlbehaviorcloningregularizeroptions.html";
if isfinite(options.ActionChangePenaltyWeight)
    for splitName=["train","validation"]
        for rowIndex=1:numel(replay.(splitName))
            r=replay.(splitName){rowIndex};
            assert(string(r.reward_profile)=="time-weighted-current-speed-v3");
            if ~isfield(r,'physical_reward'),r.physical_reward=r.reward;end
            r.pre_action_cost_reward=r.reward;
            r.reward=r.reward+(.005-options.ActionChangePenaltyWeight)*sum(r.physical_delta_action.^2);
            r.reward_profile="diagnostic-action-cost-reweight-v1";
            replay.(splitName){rowIndex}=r;
        end
    end
end
for splitName=["train","validation"]
    for rowIndex=1:numel(replay.(splitName))
        motorTD3MaskedAction(replay.(splitName){rowIndex}.action_normalized(:),actionMask);
        recorded=replay.(splitName){rowIndex}.action_normalized(:);
        assert(all(recorded>=options.ActionLowerLimit-1e-6 & recorded<=options.ActionUpperLimit+1e-6));
    end
end
if ~isfolder(outputDir),mkdir(outputDir);end
assert(options.CriticWarmStartSteps<=2000);
if options.CriticWarmStartSteps>0
    assert(options.LearningTask=="bounded-trial" && ...
        (isnan(options.ActionChangePenaltyWeight) || options.ActionChangePenaltyWeight==.005));
end
criticInitialValue=NaN;
if options.InitializeCriticFromTrainingReward
    if options.LearningTask=="bounded-trial"
        criticInitialValue=mean(cellfun(@(r)r.logged_bounded_return,replay.train));
    else
        criticInitialValue=mean(cellfun(@(r)r.reward,replay.train))/(1-.99);
    end
end
report=struct(schema_version=1,source="local-causal-real-data-td3",hardware_accessed=false, ...
    learning_contract=contract,dataset_sha256=string(physical.summary.dataset_sha256), ...
    training_experiences=numel(replay.train),validation_experiences=numel(replay.validation), ...
    actual_training_action_coverage=physical.training_action_coverage, ...
    action_mask=actionMask',behavior_cloning_weight=options.BehaviorCloningWeight,target_noise_std=([.05;.05].*actionMask)', ...
    target_noise_clip=.1,seeds=[7 17 27],steps_per_seed=options.Epochs*40,seed_reports=[], ...
    candidate_files=strings(0,1),deployment_allowed=false,performance_claim_allowed=false, ...
    ordinary_live_admission=false,thermal_gate_modified=false,td3_training_performed=false, ...
    critic_initialized_from_training_reward=options.InitializeCriticFromTrainingReward, ...
    critic_initial_value=criticInitialValue, ...
    critic_l2_regularization_factor=options.CriticL2RegularizationFactor, ...
    critic_initialization_basis="Optional mean TRAINING reward / (1-gamma); no validation labels, no terminal relabeling");
if options.LearningTask=="bounded-trial"
    report.critic_initialization_basis="Mean TRAINING logged finite return, actual experiment STOP; physical flags unchanged";
end
f=fopen(fullfile(outputDir,'study-contract.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
seedReports=cell(3,1);files=strings(3,1);
for k=1:3
    seed=report.seeds(k);
    experimentalAgent=createMotorTD3(seed,actionMask,options.BehaviorCloningWeight, ...
        TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1,CriticInitialValue=criticInitialValue, ...
        CriticL2RegularizationFactor=options.CriticL2RegularizationFactor, ...
        ActionLowerLimit=options.ActionLowerLimit,ActionUpperLimit=options.ActionUpperLimit, ...
        ActorInputMask=options.ActorInputMask);
    warmReport=struct(steps_per_critic=0,hardware_accessed=false);
    if options.CriticWarmStartSteps>0
        [networks,warmReport]=warmStartMotorCritics(experimentalAgent,replay,options.CriticWarmStartSteps,seed);
        experimentalAgent=createMotorTD3(seed,actionMask,options.BehaviorCloningWeight, ...
            TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1, ...
            CriticL2RegularizationFactor=options.CriticL2RegularizationFactor, ...
            ActionLowerLimit=options.ActionLowerLimit,ActionUpperLimit=options.ActionUpperLimit, ...
            ActorInputMask=options.ActorInputMask,InitialCriticNetworks=networks);
    end
    actor0=getModel(getActor(experimentalAgent));c0=getCritic(experimentalAgent);
    critic0={getModel(c0(1)),getModel(c0(2))};
    for j=1:numel(replay.train)
        r=replay.train{j};
        e=struct('Observation',{{single(r.observation(:))}},'Action',{{single(r.action_normalized(:))}}, ...
            'Reward',double(r.reward),'NextObservation',{{single(r.next_observation(:))}},'IsDone',double(r.learning_is_done));
        validateExperience(experimentalAgent.ExperienceBuffer,e);append(experimentalAgent.ExperienceBuffer,e);
    end
    before=diagnoseMotorTD3Policy(experimentalAgent,replay.validation,options.LearningTask);
    trainingStats=trainFromData(experimentalAgent,rlTrainingFromDataOptions('MaxEpochs',options.Epochs, ...
        'NumStepsPerEpoch',40,'Plots','none','Verbose',false,'SaveAgentCriteria','none'));
    after=diagnoseMotorTD3Policy(experimentalAgent,replay.validation,options.LearningTask);
    c=getCritic(experimentalAgent);actor=getModel(getActor(experimentalAgent));
    a=after.predictions{:,{'actor_kp_action','actor_ki_action'}}';
    state=cell2mat(cellfun(@(r)r.state(:),replay.validation,UniformOutput=false)');
    if coordinates=="absolute-target",anchor=contract.encoded_baseline_gains(:);
    else,anchor=state(8:9,:);end
    gains=anchor+a.*contract.gain_step_scale(:);
    reportSeed=struct(seed=seed,learning_contract=contract,critic_warm_start=warmReport, ...
        training_steps_total=double(trainingStats.TotalSteps(end)), ...
        actor_weight_change_l2=distance(actor0,actor), ...
        critic_weight_change_l2=[distance(critic0{1},getModel(c(1))),distance(critic0{2},getModel(c(2)))], ...
        validation_before=before.metrics,validation_after=after.metrics,epoch_q_value=double(trainingStats.QValue), ...
        critic_numerical_screen=screenMotorCriticDiagnostics(after.metrics), ...
        ki_masked=actionMask(2)==0,action_bounds_passed=all(abs(a)<=1+1e-6,'all'), ...
        gain_bounds_passed=all(gains(1,:)>=.0013556 & gains(1,:)<=.0054224 & ...
            gains(2,:)>=.00072 & gains(2,:)<=.00216), ...
        deployment_allowed=false,performance_claim_allowed=false,runtime_compatible=false);
    assert(all(abs(a(actionMask==0,:))<1e-12,'all'));
    assert(all(a>=options.ActionLowerLimit-1e-6 & a<=options.ActionUpperLimit+1e-6,'all'));
    if actionMask(2)==0,assert(all(gains(2,:)==contract.encoded_baseline_gains(2)));end
    checkpoint=fullfile(outputDir,"causal-candidate-seed-"+seed+".mat");
    save(checkpoint,'experimentalAgent','reportSeed','trainingStats');
    reportSeed.checkpoint_sha256=motorFileSHA256(checkpoint);
    exportMotorTD3DiagnosticJSON(checkpoint,fullfile(outputDir,"networks-seed-"+seed+".json"));
    after.predictions.candidate_kp=gains(1,:)';after.predictions.candidate_ki=gains(2,:)';
    after.predictions.hardware_writeback=false(height(after.predictions),1);
    writetable(after.predictions,fullfile(outputDir,"validation-seed-"+seed+".csv"));
    seedReports{k}=reportSeed;files(k)=checkpoint;
end
report.seed_reports=[seedReports{:}];report.candidate_files=files;
report.td3_training_performed=true;report.total_gradient_steps=sum([report.seed_reports.training_steps_total]);
f=fopen(fullfile(outputDir,'causal-training-summary.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
end

function d=distance(a,b)
d=0;
for k=1:height(a.Learnables)
    d=d+sum(double(extractdata(b.Learnables.Value{k}-a.Learnables.Value{k})).^2,'all');
end
d=sqrt(d);
end
