function agent = createMotorTD3(seed, actionMask, behaviorCloningWeight, options)
% Small exportable actor: 10 -> 16 ReLU -> 16 ReLU -> 2 tanh.
arguments
    seed (1,1) double
    actionMask (2,1) double = [1;1]
    behaviorCloningWeight (1,1) double = 0
    options.TargetNoiseStandardDeviation (2,1) double = sqrt(.2)*ones(2,1)
    options.TargetNoiseClip (1,1) double = .5
    options.CriticInitialValue (1,1) double = NaN
    options.CriticL2RegularizationFactor (1,1) double = 1e-4
    options.ActionLowerLimit (2,1) double = -ones(2,1)
    options.ActionUpperLimit (2,1) double = ones(2,1)
    options.ActorInputMask (10,1) double = ones(10,1)
    options.CriticInputMask (10,1) double = ones(10,1)
    options.InitialCriticNetworks cell = {}
    options.InitialNormalizedAction (2,1) double = NaN(2,1)
    options.CriticArchitecture (1,1) string {mustBeMember(options.CriticArchitecture,["concat-mlp","local-quadratic"])}="concat-mlp"
    options.CriticFeatureCenter (42,1) double=zeros(42,1)
    options.CriticFeatureScale (42,1) double=ones(42,1)
    options.CriticLearningRate (1,1) double {mustBePositive,mustBeFinite}=.001
    options.ActorLearningRate (1,1) double {mustBePositive,mustBeFinite}=.0001
end
assert(all(ismember(actionMask,[0 1])) && actionMask(1)==1);
assert(isfinite(behaviorCloningWeight) && behaviorCloningWeight>=0);
assert(all(isfinite(options.TargetNoiseStandardDeviation)) && ...
    all(options.TargetNoiseStandardDeviation>=0), 'MotorTD3:Noise', 'Invalid target noise');
assert(isfinite(options.TargetNoiseClip) && options.TargetNoiseClip>0 && ...
    options.TargetNoiseClip<=1, 'MotorTD3:Noise', 'Invalid target noise clip');
assert(isnan(options.CriticInitialValue) || isfinite(options.CriticInitialValue));
assert(isfinite(options.CriticL2RegularizationFactor) && options.CriticL2RegularizationFactor>=0);
criticL2=options.CriticL2RegularizationFactor;
criticLearningRate=options.CriticLearningRate;
actorLearningRate=options.ActorLearningRate;
assert(all(ismember(options.ActorInputMask,[0 1])) && any(options.ActorInputMask));
assert(all(ismember(options.CriticInputMask,[0 1])) && any(options.CriticInputMask));
assert(isempty(options.InitialCriticNetworks) || all(options.CriticInputMask==1), ...
    'MotorTD3:CriticMask','Explicit masked critic construction requires fresh networks');
assert(isempty(options.InitialCriticNetworks) || ...
    (numel(options.InitialCriticNetworks)==2 && all(cellfun(@(x)isa(x,'dlnetwork'),options.InitialCriticNetworks))));
actionLower=options.ActionLowerLimit;actionUpper=options.ActionUpperLimit;
assert(all(isfinite([actionLower;actionUpper])) && all(actionLower<actionUpper));
assert(all(actionLower>=-1 & actionUpper<=1) && ...
    all(actionLower(actionMask==0)<=0 & actionUpper(actionMask==0)>=0));
assert(all(isnan(options.InitialNormalizedAction)) || ...
    (all(isfinite(options.InitialNormalizedAction)) && ...
    all(options.InitialNormalizedAction>=actionLower & options.InitialNormalizedAction<=actionUpper)));
rng(seed, 'twister');
obs = rlNumericSpec([10 1]);
act = rlNumericSpec([2 1], 'LowerLimit',actionLower, 'UpperLimit',actionUpper);
actorLayers=featureInputLayer(10,'Normalization','none','Name','state');
if any(options.ActorInputMask==0)
    inputMask=single(options.ActorInputMask);
    actorLayers=[actorLayers;functionLayer(@(x)x.*inputMask, ...
        'Name','actor_input_mask','Formattable',true)];
end
actorNet = dlnetwork([actorLayers
    fullyConnectedLayer(16,'Name','fc1')
    reluLayer('Name','relu1')
    fullyConnectedLayer(16,'Name','fc2')
    reluLayer('Name','relu2')
    fullyConnectedLayer(2,'Name','fc3')
    tanhLayer('Name','bounded_action')]);
% Initial behavior near hold-gains; no full-range random warm start.
values = actorNet.Learnables;
for i = 1:height(values)
    if values.Layer(i) == "fc3"
        if values.Parameter(i) == "Weights"
            actorNet.Learnables.Value{i} = values.Value{i} * single(.01);
        else
            actorNet.Learnables.Value{i} = values.Value{i} * single(0);
        end
    end
end
if all(isfinite(options.InitialNormalizedAction))
    % Affine one-sided ranges map tanh(0) to their midpoint, not baseline.
    % Stay just inside tanh endpoints so policy gradients remain finite.
    initialTanh=(options.InitialNormalizedAction-(actionUpper+actionLower)/2)./((actionUpper-actionLower)/2);
    initialBias=single(atanh(max(-.99,min(.99,initialTanh))));
    for i=1:height(actorNet.Learnables)
        if actorNet.Learnables.Layer(i)=="fc3" && actorNet.Learnables.Parameter(i)=="Bias"
            actorNet.Learnables.Value{i}=actorNet.Learnables.Value{i}*single(0)+initialBias;
        end
    end
end
outputName='bounded_action';
if any(actionLower~=-1 | actionUpper~=1)
    actionScale=single((actionUpper-actionLower)/2);
    actionBias=single((actionUpper+actionLower)/2);
    actorNet=addLayers(actorNet,functionLayer(@(x)x.*actionScale+actionBias, ...
        'Name','supported_action_range','Formattable',true));
    actorNet=connectLayers(actorNet,outputName,'supported_action_range');
    outputName='supported_action_range';
end
if any(actionMask==0)
    actorNet=addLayers(actorNet,functionLayer(@(x)x.*single(actionMask), ...
        'Name','fixed_action_mask','Formattable',true));
    actorNet=connectLayers(actorNet,outputName,'fixed_action_mask');
end
actor = rlContinuousDeterministicActor(actorNet,obs,act, 'ObservationInputNames','state');
if isempty(options.InitialCriticNetworks)
    if options.CriticArchitecture=="local-quadratic"
        assert(actionMask(2)==0,'MotorTD3:QuadraticMask','Local quadratic Critic supports fixed Ki only');
        critic1=createMotorLocalQuadraticCritic(obs,act,options.CriticInitialValue,options.CriticInputMask,options.CriticFeatureCenter,options.CriticFeatureScale);
        critic2=createMotorLocalQuadraticCritic(obs,act,options.CriticInitialValue,options.CriticInputMask,options.CriticFeatureCenter,options.CriticFeatureScale);
    else
        critic1 = makeCritic(obs,act,options.CriticInitialValue,options.CriticInputMask);
        critic2 = makeCritic(obs,act,options.CriticInitialValue,options.CriticInputMask);
    end
else
    critic1=rlQValueFunction(options.InitialCriticNetworks{1},obs,act, ...
        'ObservationInputNames','state','ActionInputNames','action');
    critic2=rlQValueFunction(options.InitialCriticNetworks{2},obs,act, ...
        'ObservationInputNames','state','ActionInputNames','action');
end
noiseStd=options.TargetNoiseStandardDeviation;
noiseClip=options.TargetNoiseClip;
options = rlTD3AgentOptions('MiniBatchSize',32, 'ExperienceBufferLength',10000, ...
    'NumWarmStartSteps',32, 'DiscountFactor',.99, 'PolicyUpdateFrequency',2, ...
    'TargetSmoothFactor',.005, 'ResetExperienceBufferBeforeTraining',false);
options.ActorOptimizerOptions.LearnRate = actorLearningRate;
options.CriticOptimizerOptions(1).LearnRate = criticLearningRate;
options.CriticOptimizerOptions(2).LearnRate = criticLearningRate;
options.CriticOptimizerOptions(1).L2RegularizationFactor=criticL2;
options.CriticOptimizerOptions(2).L2RegularizationFactor=criticL2;
options.TargetPolicySmoothModel.StandardDeviationMin=min(.1,noiseStd/2).*actionMask;
options.TargetPolicySmoothModel.StandardDeviation=noiseStd.*actionMask;
options.TargetPolicySmoothModel.LowerLimit=-noiseClip;
options.TargetPolicySmoothModel.UpperLimit=noiseClip;
options.ExplorationModel.StandardDeviationMin=options.ExplorationModel.StandardDeviationMin.*actionMask;
options.ExplorationModel.StandardDeviation=options.ExplorationModel.StandardDeviation.*actionMask;
if behaviorCloningWeight>0
    % MathWorks Wbc scales the RL term, not the imitation term:
    % lambda=Wbc/mean(abs(Q)); BC is range-scaled by (2/(upper-lower))^2.
    % Raising this positive option increases RL relative to imitation.
    % Exactly zero here disables the regularizer (a separate code path).
    options.BatchDataRegularizerOptions=rlBehaviorCloningRegularizerOptions( ...
        BehaviorCloningRegularizerWeight=behaviorCloningWeight);
end
agent = rlTD3Agent(actor,[critic1 critic2],options);
agent.UseExplorationPolicy = false;
end

function critic = makeCritic(obs,act,initialValue,inputMask)
net = dlnetwork;
net = addLayers(net, featureInputLayer(10,'Normalization','none','Name','state'));
net = addLayers(net, featureInputLayer(2,'Normalization','none','Name','action'));
net = addLayers(net, [concatenationLayer(1,2,'Name','join')
    fullyConnectedLayer(32,'Name','c1'); reluLayer('Name','r1')
    fullyConnectedLayer(32,'Name','c2'); reluLayer('Name','r2')
    fullyConnectedLayer(1,'Name','q')]);
if any(inputMask==0)
    frozenMask=single(inputMask);
    net=addLayers(net,functionLayer(@(x)x.*frozenMask,'Name','critic_state_mask','Formattable',true));
    net=connectLayers(net,'state','critic_state_mask');
    net=connectLayers(net,'critic_state_mask','join/in1');
else
    net = connectLayers(net,'state','join/in1');
end
net = connectLayers(net,'action','join/in2');
net = initialize(net);
% Optional continuing-task prior from TRAINING rewards only. Preserve the
% legacy random initialization exactly when this option is not supplied.
if isfinite(initialValue)
    for k=1:height(net.Learnables)
        if net.Learnables.Layer(k)=="q"
            if net.Learnables.Parameter(k)=="Bias"
                net.Learnables.Value{k}=net.Learnables.Value{k}*single(0)+single(initialValue);
            else
                net.Learnables.Value{k}=net.Learnables.Value{k}*single(.01);
            end
        end
    end
end
critic = rlQValueFunction(net,obs,act,'ObservationInputNames','state','ActionInputNames','action');
end
