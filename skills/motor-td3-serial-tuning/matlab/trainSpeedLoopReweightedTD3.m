function report = trainSpeedLoopReweightedTD3(runDirs, outputDir, allowExperimentalShadow, seeds)
% Train experimental TD3 candidates with stronger current/speed penalties.
% This is offline only: it never opens hardware, applies gains, or grants
% ordinary live admission. Ki is fixed to zero action and baseline Ki.
arguments
    runDirs (:,1) string
    outputDir (1,1) string
    allowExperimentalShadow (1,1) logical = false
    seeds (:,1) double = [7;17;27]
end
assert(allowExperimentalShadow,"Explicit experimental shadow-analysis selection required");
assert(~isempty(runDirs) && ~isempty(seeds));
if ~isfolder(outputDir), mkdir(outputDir); end

allRows = cell(0,1);
hashes = strings(0,1);
boots = strings(0,1);
auditReports = cell(numel(runDirs),1);
for trialIndex = 1:numel(runDirs)
    auditDir = fullfile(outputDir,"audit-"+trialIndex);
    audit = auditSpeedLoopClosedLoopTrial(runDirs(trialIndex),auditDir);
    assert(string(audit.firmware_id)=="g431-speedloop-pi-motion-v5");
    assert(string(audit.bin_sha256)== ...
        "45ad8fcd5039822741d888cb54eaea909cfc55d3e13dc8da0cdfcfc98703cce5");
    assert(audit.all_telemetry_faults_zero && audit.stop_and_physical_shutdown_verified);
    raw = fileread(fullfile(runDirs(trialIndex),"telemetry.jsonl"));
    lines = splitlines(strtrim(raw));
    first = jsondecode(string(lines(1)));
    boot = string(first.boot_id);
    hash = string(sha256(replace(string(raw),sprintf('\r\n'),newline)));
    assert(~any(hashes==hash) && ~any(boots==boot), ...
        "Duplicate physical trial cannot multiply replay data");
    hashes(end+1,1)=hash; boots(end+1,1)=boot; %#ok<AGROW>
    candidateLines = splitlines(strtrim(fileread(fullfile(auditDir, ...
        "experience-candidates.jsonl"))));
    candidates = cellfun(@jsondecode,cellstr(candidateLines),UniformOutput=false);
    candidates = candidates(cellfun(@(r)r.stage_confirmed_from_raw_edges,candidates));
    assert(~isempty(candidates),"No directly stage-confirmed action windows");
    for step = 1:numel(candidates)
        r = candidates{step};
        assert(~r.learner_eligible);
        if step>1
            previous = candidates{step-1};
            assert(r.t_state_us==previous.t_next_us && isequal(r.state,previous.next_state));
            assert(r.command_seq>previous.command_seq);
        end
        assert(r.t_state_us<=r.t_apply_us && r.t_apply_us<r.t_next_us);
        assert(numel(r.observation)==10 && numel(r.action_normalized)==2);
        assert(all(isfinite([r.observation(:);r.next_observation(:); ...
            r.action_normalized(:);r.reward])));
        assert(all(abs(r.action_normalized)<=1+1e-6) && r.max_frame_gap_ms<=40);
        assert(isfield(r,"response_rmse_rpm") && isfield(r,"response_peak_current_a"));
        assert(isfield(r,"response_peak_speed_rpm") && isfield(r,"response_saturation_ratio"));
        r.legacy_reward = r.reward;
        r.reward = reweightedReward(r);
        r.reward_profile = "current-speed-penalty-v2";
        r.reward_weights = struct(error=1,current=0.12,near_speed_limit=0.08, ...
            saturation=0.10,action=0.005,near_speed_threshold_rpm=1500, ...
            near_speed_scale_rpm=300);
        r.run_index=trialIndex;
        r.step=step-1;
        r.boot_id=boot;
        r.validation_split = mod(trialIndex,5)==0 || trialIndex==numel(runDirs);
        r.analysis_mode="experimental-reweighted-offline-shadow";
        r.shadow_learner_eligible=true;
        r.ordinary_live_learner_eligible=false;
        r.truncated=step==numel(candidates);
        r.terminated=false;
        allRows{end+1,1}=r; %#ok<AGROW>
    end
    auditReports{trialIndex}=audit;
end

validation = cellfun(@(r)r.validation_split,allRows);
trainRows = allRows(~validation);
validationRows = allRows(validation);
assert(numel(trainRows)>=128,"Training split is below TD3 warmup");
assert(~isempty(validationRows),"Validation split is empty");
writeRows(fullfile(outputDir,"reweighted-transitions.jsonl"),allRows);

seedReports = cell(numel(seeds),1);
candidateFiles = strings(numel(seeds),1);
for seedIndex=1:numel(seeds)
    seed = seeds(seedIndex);
    agent = createMotorTD3(seed);
    for index=1:numel(trainRows)
        r=trainRows{index};
        experience=struct('Observation',{{single(r.observation(:))}}, ...
            'Action',{{single(r.action_normalized(:))}}, ...
            'Reward',double(r.reward), ...
            'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
        validateExperience(agent.ExperienceBuffer,experience);
        append(agent.ExperienceBuffer,experience);
    end
    options=rlTrainingFromDataOptions('MaxEpochs',2,'NumStepsPerEpoch',40, ...
        'Plots','none','Verbose',false,'SaveAgentCriteria','none');
    trainingStats=trainFromData(agent,options);
    [predictions,checks]=predictMaskedActor(agent,validationRows);
    file=fullfile(outputDir,"reweighted-candidate-seed-"+seed+".mat");
    reportSeed=struct(seed=seed,train_experiences=numel(trainRows), ...
        validation_experiences=numel(validationRows), ...
        training_steps=double(trainingStats.TotalSteps), ...
        training_steps_total=double(trainingStats.TotalSteps(end)), ...
        validation_action_min=min(predictions,[],1), ...
        validation_action_max=max(predictions,[],1), ...
        action_bounds_passed=checks.action_bounds_passed, ...
        gain_bounds_passed=checks.gain_bounds_passed, ...
        ki_masked=true,offline_performance_verified=false, ...
        deployment_allowed=false,performance_claim_allowed=false);
    seedReports{seedIndex}=reportSeed;
    candidateFiles(seedIndex)=string(file);
    save(file,'agent','reportSeed','trainingStats');
end

datasetText = fileread(fullfile(outputDir,"reweighted-transitions.jsonl"));
kpSeedMeans = cellfun(@(s)mean([s.validation_action_min(1), ...
    s.validation_action_max(1)]),seedReports);
seedDirectionConsistent = all(kpSeedMeans>=0) || all(kpSeedMeans<=0);
report=struct(schema_version=1,source="real_motor",simulation_only=false, ...
    mode="experimental-reweighted-offline-shadow",hardware_accessed=false, ...
    matlab_release=string(version("-release")),physical_trials=numel(runDirs), ...
    replay_experiences=numel(allRows),training_experiences=numel(trainRows), ...
    validation_experiences=numel(validationRows),replay_warmup_required=128, ...
    training_seed_values=seeds(:).',seed_reports=[seedReports{:}], ...
    seed_kp_action_means=kpSeedMeans,seed_kp_action_direction_consistent=seedDirectionConsistent, ...
    candidate_files=candidateFiles,action_mask=[1 0],ki_fixed_baseline=.00144, ...
    ki_exploration_performed=false,legacy_reward_preserved=true, ...
    reward_profile="current-speed-penalty-v2", ...
    deployment_allowed=false,performance_claim_allowed=false, ...
    offline_performance_verified=false,needs_physical_validation=true, ...
    ordinary_live_admission=false,thermal_gate_modified=false, ...
    temperature_c=NaN,current_conversion_independently_calibrated=false, ...
    telemetry_sha256=hashes,boot_ids=boots,dataset_sha256=string(sha256(datasetText)), ...
    hash_convention="UTF-8 with LF line endings; field content unchanged", ...
    state_fields=auditReports{1}.state_fields,state_scale=auditReports{1}.state_scale, ...
    acceptance_rule="Require >=5 percent holdout RMSE improvement without current or peak-speed increase; physical evidence still required", ...
    recommendation="hold_baseline_PI_until_unseen_physical_validation");
writeUTF8(fullfile(outputDir,"reweighted-training-summary.json"), ...
    string(jsonencode(report,PrettyPrint=true))+newline);
save(fullfile(outputDir,"reweighted-training-report.mat"),'report','auditReports','seedReports');
end

function reward = reweightedReward(r)
err = double(r.response_rmse_rpm)/1000;
current = double(r.response_peak_current_a)/2;
nearLimit = max(0,(double(r.response_peak_speed_rpm)-1500)/300);
sat = double(r.response_saturation_ratio);
action = double(r.action_normalized);
reward = -err^2 - .12*current^2 - .08*nearLimit^2 - .10*sat - .005*sum(action.^2);
end

function [predictions,checks] = predictMaskedActor(agent,rows)
predictions=zeros(numel(rows),2);
for index=1:numel(rows)
    a=getAction(getActor(agent),{single(rows{index}.observation(:))});
    predictions(index,:)=double(a{1}(:)).';
end
predictions(:,2)=0; % Ki is unobserved and must remain fixed.
checks.action_bounds_passed=all(abs(predictions(:))<=1+1e-6);
checks.gain_bounds_passed=true;
for index=1:numel(rows)
    kp=double(rows{index}.state(8));
    kpAction=predictions(index,1);
    if kpAction>=0
        gain=kp+(min(.0054224,kp+.00027112)-kp)*kpAction;
    else
        gain=kp+(kp-max(.0013556,kp-.00027112))*kpAction;
    end
    if ~(gain>=.0013556 && gain<=.0054224)
        checks.gain_bounds_passed=false;
    end
end
end

function writeRows(path,rows)
fid=fopen(path,"w","n","UTF-8"); assert(fid>=0);
closer=onCleanup(@()fclose(fid)); %#ok<NASGU>
for index=1:numel(rows), fprintf(fid,"%s\n",jsonencode(rows{index})); end
end

function value=sha256(text)
digest=java.security.MessageDigest.getInstance('SHA-256');
digest.update(unicode2native(char(text),'UTF-8'));
bytes=typecast(digest.digest(),'uint8');
value=lower(reshape(dec2hex(bytes,2).',1,[]));
end

function writeUTF8(path,text)
fid=fopen(path,'wb'); assert(fid>=0);
closer=onCleanup(@()fclose(fid)); %#ok<NASGU>
fwrite(fid,unicode2native(char(text),'UTF-8'),'uint8');
end
