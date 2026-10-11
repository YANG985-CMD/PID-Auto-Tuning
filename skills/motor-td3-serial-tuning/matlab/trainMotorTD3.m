function report = trainMotorTD3(port, tokenFile, outputDir, rounds)
% Actual MATLAB RL Toolbox TD3 updates from bridge-confirmed experiences.
% Hardware collection uses only the explicitly selected behavior actor. A newly
% trained candidate never replaces that live behavior actor automatically.
arguments
    port (1,1) double
    tokenFile (1,:) char
    outputDir (1,:) char
    rounds (1,1) double {mustBeInteger,mustBePositive} = 6
end
if ~isfolder(outputDir), mkdir(outputDir); end
client = MotorTD3Client(port,tokenFile);
cleanup = onCleanup(@() safeStop(client));
profile = client.Profile;
agent = createMotorTD3(7);
initial = getModel(getActor(agent));
initialValues = initial.Learnables;
episodeRewards = zeros(rounds,1);
bufferLengths = zeros(rounds,1);
actionKeys = strings(0,1);
behavior = getActor(agent);
version = 'candidate-000';
if ~client.SimulationOnly
    % Start live collection with the verified fixed PI behavior, using only
    % small bounded exploration. This does not send an unreviewed trained actor.
    version = 'baseline';
end
for roundIndex = 1:rounds
    refIndex = mod(roundIndex-1, numel(profile.runtime.speed_refs_rpm));
    reset = client.call(struct('op','reset','seed',roundIndex, ...
        'ref_index',refIndex,'policy_version',version));
    obs = single(reset.observation(:));
    while true
        if client.SimulationOnly
            chosen = getAction(behavior,{obs});
            action = double(chosen{1}(:));
        else
            action = zeros(2,1);
        end
        % Exploration coordinate is part of the actual causal action.
        noise = .1 * randn(2,1);
        if ~client.SimulationOnly, noise = .03 * randn(2,1); end
        if client.SimulationOnly
            % The action is a local gain step. Independent zero-mean noise
            % mostly returns to the baseline and does not cover the validated
            % gain rectangle. Use a bounded, episode-level direction only in
            % the mock plant; live hardware keeps the conservative noise path.
            directions = [1 1; 1 -1; -1 1; -1 -1; 1 1; -1 -1];
            direction = directions(mod(roundIndex-1,size(directions,1))+1,:).';
            coverage = .65 * direction;
            action = max(-1,min(1,.45*action + .55*coverage + noise));
        end
        action = max(-1,min(1,action + noise));
        reply = client.call(struct('op','step','action',action(:)'));
        row = reply.transition;
        actionKeys(end+1,1) = string(sprintf('%.9g,%.9g', ...
            row.action_applied.kp, row.action_applied.ki)); %#ok<AGROW>
        if ~row.learner_eligible || row.safety_intervention || row.terminated
            error('MotorTD3:InvalidExperience','Excluded/unknown endpoint cannot enter replay');
        end
        next = single(reply.observation(:));
        experience = struct('Observation',{{obs}}, 'Action',{{single(action)}}, ...
            'Reward',double(reply.reward), 'NextObservation',{{next}}, ...
            'IsDone',double(reply.terminated));
        % A time limit is truncated, not a terminal state: bootstrap is retained.
        validateExperience(agent.ExperienceBuffer,experience);
        append(agent.ExperienceBuffer,experience);
        episodeRewards(roundIndex) = episodeRewards(roundIndex) + reply.reward;
        obs = next;
        if reply.truncated || reply.terminated, break; end
    end
    client.stop(); % Fresh disabled feedback required by bridge before learning.
    bufferLengths(roundIndex) = agent.ExperienceBuffer.Length;
    if agent.ExperienceBuffer.Length >= 128
        if client.SimulationOnly
            % The mock experiment has cheap, reproducible data. More updates
            % let the critics learn the effect of the local-step action map.
            epochs = 3; stepsPerEpoch = 100;
        else
            epochs = 1; stepsPerEpoch = 20;
        end
        options = rlTrainingFromDataOptions('MaxEpochs',epochs,'NumStepsPerEpoch',stepsPerEpoch, ...
            'Plots','none','Verbose',false,'SaveAgentCriteria','none');
        stats = trainFromData(agent,options); %#ok<NASGU>
    end
    versionNext = sprintf('candidate-%03d',roundIndex);
    save(fullfile(outputDir, [versionNext '.mat']), 'agent','profile','versionNext');
    if client.SimulationOnly
        behavior = getActor(agent);
        version = versionNext;
    end
    fprintf('TD3 round %d/%d, actual replay experiences %d, reward %.4f\n', ...
        roundIndex,rounds,bufferLengths(roundIndex),episodeRewards(roundIndex));
end
dataset = client.metadata();
final = getModel(getActor(agent));
delta = 0;
for i = 1:height(initialValues)
    delta = delta + sum(double(extractdata(final.Learnables.Value{i} - initialValues.Value{i})).^2,'all');
end
report = struct('schema_version',1,'simulation_only',client.SimulationOnly, ...
    'matlab_release',versionRelease(), 'rounds',rounds, ...
    'replay_experiences',agent.ExperienceBuffer.Length, ...
    'actor_weight_change_l2',sqrt(delta),'episode_rewards',episodeRewards, ...
    'policy_version',versionNext,'gradient_updates_while_motor_stopped',true, ...
    'live_candidate_auto_applied',false, ...
    'reward_design','tracking_plus_current_mse_plus_peak_current_plus_overshoot_plus_saturation', ...
    'exploration_strategy', ternary(client.SimulationOnly, ...
        'bounded_directional_coverage_plus_noise', 'small_zero_mean_noise'), ...
    'training_schedule', ternary(client.SimulationOnly, ...
        'replay_warmup_128_epochs_3_steps_per_epoch_100', ...
        'replay_warmup_128_epochs_1_steps_per_epoch_20'));
report.training_data = struct( ...
    'source', ternary(client.SimulationOnly,'mock','real_motor'), ...
    'dataset_sha256', char(dataset.transitions_sha256), ...
    'profile_id', profile.profile_id, ...
    'firmware_id', profile.device.firmware_id, ...
    'protocol_id', profile.device.protocol_id, ...
    'eligible_transitions', agent.ExperienceBuffer.Length, ...
    'episodes', rounds, ...
    'action_unique_count', numel(unique(actionKeys)), ...
    'hash_note', 'SHA-256 of the flushed bridge transitions.jsonl; Codex must re-hash before deployment');
report.realtime_closed_loop = logical(~client.SimulationOnly);
report.bridge_transition_count = double(dataset.transition_count);
report.bridge_transport = char(dataset.transport);
save(fullfile(outputDir,'trained-agent.mat'),'agent','profile','report');
writeJSON(fullfile(outputDir,'training-summary.json'),report);
exportMotorActor(agent,profile,fullfile(outputDir,'actor'),versionNext,report.training_data);
if client.SimulationOnly
    evaluation = evaluateMotorTD3(client,agent,versionNext);
    writeJSON(fullfile(outputDir,'evaluation-summary.json'),evaluation);
end
clear cleanup
end

function value = ternary(condition, whenTrue, whenFalse)
if condition
    value = whenTrue;
else
    value = whenFalse;
end
end

function release = versionRelease()
release = version('-release');
end

function safeStop(client)
try
    client.stop();
catch exception
    warning('MotorTD3:StopUnconfirmed','%s',exception.message);
end
end

function writeJSON(path,value)
fid = fopen(path,'w','n','UTF-8');
assert(fid >= 0,'Cannot open report');
closer = onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(value,'PrettyPrint',true));
end
