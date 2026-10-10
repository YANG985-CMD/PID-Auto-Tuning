function agent = createMotorTD3(seed)
% Small exportable actor: 10 -> 16 ReLU -> 16 ReLU -> 2 tanh.
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
actor = rlContinuousDeterministicActor(actorNet,obs,act, 'ObservationInputNames','state');
critic1 = makeCritic(obs,act);
critic2 = makeCritic(obs,act);
options = rlTD3AgentOptions('MiniBatchSize',32, 'ExperienceBufferLength',10000, ...
    'NumWarmStartSteps',32, 'DiscountFactor',.99, 'PolicyUpdateFrequency',2, ...
    'TargetSmoothFactor',.005, 'ResetExperienceBufferBeforeTraining',false);
options.ActorOptimizerOptions.LearnRate = 1e-4;
options.CriticOptimizerOptions(1).LearnRate = 1e-3;
options.CriticOptimizerOptions(2).LearnRate = 1e-3;
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
