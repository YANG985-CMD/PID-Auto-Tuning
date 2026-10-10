function report = evaluateMotorTD3(client, agent, policyVersion)
% Independent deterministic fixtures, exploration off, same baseline/reset.
actor = getActor(agent);
fixtures = [101 202 303];
rows = repmat(struct('policy','','seed',0,'reward',0,'rmse_normalized',0, ...
    'peak_current_a',0,'overshoot_rpm',0,'saturation_fraction',0,'fault_count',0),1,6);
for method = 1:2
    for j = 1:numel(fixtures)
        identity = 'baseline';
        if method == 2, identity = policyVersion; end
        reset = client.call(struct('op','reset','seed',fixtures(j), ...
            'ref_index',mod(j-1,numel(client.Profile.runtime.speed_refs_rpm)), ...
            'policy_version',identity));
        obs = single(reset.observation(:));
        score = 0; errors = []; peaks = []; overshoot = []; saturation = [];
        while true
            action = zeros(2,1);
            if method == 2
                chosen = getAction(actor,{obs});
                action = double(chosen{1}(:));
            end
            result = client.call(struct('op','step','action',action(:)'));
            score = score + result.reward;
            m = result.transition.metrics;
            errors(end+1) = m.error_mse_normalized; %#ok<AGROW>
            peaks(end+1) = m.peak_current_a; %#ok<AGROW>
            overshoot(end+1) = m.overshoot_rpm; %#ok<AGROW>
            saturation(end+1) = m.saturation_fraction; %#ok<AGROW>
            obs = single(result.observation(:));
            if result.truncated || result.terminated, break; end
        end
        client.stop();
        rows((method-1)*3+j) = struct('policy',identity,'seed',fixtures(j), ...
            'reward',score,'rmse_normalized',sqrt(mean(errors)), ...
            'peak_current_a',max(peaks),'overshoot_rpm',max(overshoot), ...
            'saturation_fraction',mean(saturation),'fault_count',0);
    end
end
base = mean([rows(1:3).rmse_normalized]);
candidate = mean([rows(4:6).rmse_normalized]);
report = struct('schema_version',1,'simulation_only',client.SimulationOnly, ...
    'exploration_enabled',false,'fixtures',rows,'baseline_mean_rmse',base, ...
    'candidate_mean_rmse',candidate, 'candidate_rmse_better',candidate < base, ...
    'hardware_deployment_approved',false, ...
    'scope','Mock plant comparison; no hardware performance or stability claim');
end
