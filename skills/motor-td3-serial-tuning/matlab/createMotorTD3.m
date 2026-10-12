function agent = createMotorTD3(seed, actionMask, behaviorCloningWeight, options)
% Small exportable actor: 10 -> 16 ReLU -> 16 ReLU -> 2 tanh.
arguments
    seed (1,1) double
    actionMask (2,1) double = [1;1]
    behaviorCloningWeight (1,1) double = 0
    options.TargetNoiseStandardDeviation (2,1) double = sqrt(.2)*ones(2,1)
    options.TargetNoiseClip (1,1) double = .5
end
assert(all(ismember(actionMask,[0 1])) && actionMask(1)==1);
assert(isfinite(behaviorCloningWeight) && behaviorCloningWeight>=0);
assert(all(isfinite(options.TargetNoiseStandardDeviation)) && ...
    all(options.TargetNoiseStandardDeviation>=0), 'MotorTD3:Noise', 'Invalid target noise');
assert(isfinite(options.TargetNoiseClip) && options.TargetNoiseClip>0 && ...
    options.TargetNoiseClip<=1, 'MotorTD3:Noise', 'Invalid target noise clip');
rng(seed, 'twister');
obs = rlNumericSpec([10 1]);
act = rlNumericSpec([2 1], 'LowerLimit',-ones(2,1), 'UpperLimit',ones(2,1));
actorNet = dlnetwork([
    featureInputLayer(10,'Normalization','none','Name','state')
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
if any(actionMask==0)
    actorNet=addLayers(actorNet,functionLayer(@(x)x.*single(actionMask), ...
        'Name','fixed_action_mask','Formattable',true));
    actorNet=connectLayers(actorNet,'bounded_action','fixed_action_mask');
end
actor = rlContinuousDeterministicActor(actorNet,obs,act, 'ObservationInputNames','state');
critic1 = makeCritic(obs,act);
critic2 = makeCritic(obs,act);
noiseStd=options.TargetNoiseStandardDeviation;
noiseClip=options.TargetNoiseClip;
options = rlTD3AgentOptions('MiniBatchSize',32, 'ExperienceBufferLength',10000, ...
    'NumWarmStartSteps',32, 'DiscountFactor',.99, 'PolicyUpdateFrequency',2, ...
    'TargetSmoothFactor',.005, 'ResetExperienceBufferBeforeTraining',false);
options.ActorOptimizerOptions.LearnRate = 1e-4;
options.CriticOptimizerOptions(1).LearnRate = 1e-3;
options.CriticOptimizerOptions(2).LearnRate = 1e-3;
options.TargetPolicySmoothModel.StandardDeviationMin=min(.1,noiseStd/2).*actionMask;
options.TargetPolicySmoothModel.StandardDeviation=noiseStd.*actionMask;
options.TargetPolicySmoothModel.LowerLimit=-noiseClip;
options.TargetPolicySmoothModel.UpperLimit=noiseClip;
options.ExplorationModel.StandardDeviationMin=options.ExplorationModel.StandardDeviationMin.*actionMask;
options.ExplorationModel.StandardDeviation=options.ExplorationModel.StandardDeviation.*actionMask;
if behaviorCloningWeight>0
    options.BatchDataRegularizerOptions=rlBehaviorCloningRegularizerOptions( ...
        BehaviorCloningRegularizerWeight=behaviorCloningWeight);
end
agent = rlTD3Agent(actor,[critic1 critic2],options);
agent.UseExplorationPolicy = false;
end

function critic = makeCritic(obs,act)
net = dlnetwork;
net = addLayers(net, featureInputLayer(10,'Normalization','none','Name','state'));
net = addLayers(net, featureInputLayer(2,'Normalization','none','Name','action'));
net = addLayers(net, [concatenationLayer(1,2,'Name','join')
    fullyConnectedLayer(32,'Name','c1'); reluLayer('Name','r1')
    fullyConnectedLayer(32,'Name','c2'); reluLayer('Name','r2')
    fullyConnectedLayer(1,'Name','q')]);
net = connectLayers(net,'state','join/in1');
net = connectLayers(net,'action','join/in2');
net = initialize(net);
critic = rlQValueFunction(net,obs,act,'ObservationInputNames','state','ActionInputNames','action');
end
