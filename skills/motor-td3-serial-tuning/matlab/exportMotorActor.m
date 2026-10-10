function artifact = exportMotorActor(agent, profile, outputDir, policyVersion)
% Export only this exact feedforward architecture, not arbitrary RL networks.
if ~isfolder(outputDir), mkdir(outputDir); end
net = getModel(getActor(agent));
expected = {'state','fc1','relu1','fc2','relu2','fc3','bounded_action'};
assert(isequal({net.Layers.Name}, expected), 'Unsupported Actor architecture');
weights = cell(1,3); biases = cell(1,3);
for i = 1:3
    layer = net.Layers(strcmp({net.Layers.Name},sprintf('fc%d',i)));
    weights{i} = double(layer.Weights);
    biases{i} = double(layer.Bias);
end
artifact = struct('schema_version',1,'policy_version',policyVersion, ...
    'profile_id',profile.profile_id,'normalization_id',profile.training.normalization_id, ...
    'action_mapping_id',profile.training.action_mapping_id, ...
    'architecture','10-16-relu-16-relu-2-tanh', ...
    'state_fields',{cellstr(string(profile.training.state_fields))'}, ...
    'state_scale',profile.runtime.state_scale(:)', ...
    'weights',{weights},'biases',{biases},'controller',profile.controller, ...
    'simulation_only',profile.simulation_only, 'hardware_deployment_approved',false);
path = fullfile(outputDir,'actor.json');
fid = fopen(path,'w'); assert(fid >= 0); cleaner = onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(artifact,'PrettyPrint',true));
clear cleaner
% Reference outputs include normalization and the same local gain mapping.
rng(913,'twister');
vectors = repmat(struct('raw_state',[],'action',[],'gains',[]),40,1);
for n = 1:40
    raw = (rand(10,1) * 4 - 2) .* single(profile.runtime.state_scale(:));
    for g = 1:2
        name = {'kp','ki'}; key = name{g};
        raw(7+g) = single(profile.controller.([key '_min']) + rand * ...
            (profile.controller.([key '_max']) - profile.controller.([key '_min'])));
    end
    if n == 1, raw(1) = single(20 * profile.runtime.state_scale(1)); end
    obs = max(-5,min(5,raw ./ single(profile.runtime.state_scale(:))));
    chosen = getAction(getActor(agent),{single(obs)});
    action = double(chosen{1}(:));
    gains = zeros(2,1);
    for g = 1:2
        name = {'kp','ki'}; key = name{g}; value = double(raw(7+g));
        lo = max(profile.controller.([key '_min']),value-profile.controller.(['max_' key '_step']));
        hi = min(profile.controller.([key '_max']),value+profile.controller.(['max_' key '_step']));
        if action(g) >= 0, delta = (hi-value)*action(g); else, delta = (value-lo)*action(g); end
        rounded = single(value + delta);
        if double(rounded) > hi, rounded = rounded - eps(rounded); end
        if double(rounded) < lo, rounded = rounded + eps(rounded); end
        gains(g) = double(rounded);
    end
    vectors(n).raw_state = double(raw(:))';
    vectors(n).action = action(:)';
    vectors(n).gains = gains(:)';
end
fid = fopen(fullfile(outputDir,'matlab-reference.json'),'w'); assert(fid >= 0);
cleaner = onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(vectors,'PrettyPrint',true));
end
