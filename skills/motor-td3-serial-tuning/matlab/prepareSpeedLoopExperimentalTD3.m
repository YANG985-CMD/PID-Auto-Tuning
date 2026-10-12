function report = prepareSpeedLoopExperimentalTD3(runDirs, outputDir, allowExperimentalShadow)
% Load audited physical trial windows into a MATLAB TD3 experimental buffer.
% This separate offline analysis entry never opens hardware or admits a live
% policy. Ordinary training/safety gates and SKILL.md remain unchanged.
arguments
    runDirs (:,1) string
    outputDir (1,1) string
    allowExperimentalShadow (1,1) logical = false
end
assert(allowExperimentalShadow,"Explicit experimental shadow-analysis selection required");
assert(~isempty(runDirs),"No physical trials supplied");
if ~isfolder(outputDir), mkdir(outputDir); end
agent = createMotorTD3(7);
initial = getModel(getActor(agent)); initialValues = initial.Learnables;
criticsInitial=getCritic(agent); criticValues=cell(1,2);
for k=1:2, network=getModel(criticsInitial(k)); criticValues{k}=network.Learnables; end
hashes = strings(0,1); boots = strings(0,1); rows = cell(0,1);
auditReports = cell(numel(runDirs),1);
for trialIndex = 1:numel(runDirs)
    runDir = runDirs(trialIndex);
    auditDir = fullfile(outputDir,"audit-"+trialIndex);
    audit = auditSpeedLoopClosedLoopTrial(runDir,auditDir);
    assert(string(audit.firmware_id)=="g431-speedloop-pi-motion-v5");
    assert(string(audit.bin_sha256)=="45ad8fcd5039822741d888cb54eaea909cfc55d3e13dc8da0cdfcfc98703cce5");
    assert(audit.all_telemetry_faults_zero && audit.stop_and_physical_shutdown_verified);
    raw = fileread(fullfile(runDir,"telemetry.jsonl")); lines = splitlines(strtrim(raw));
    first = jsondecode(string(lines(1))); boot = string(first.boot_id);
    hash = string(sha256(replace(string(raw),sprintf('\r\n'),newline)));
    assert(~any(hashes==hash) && ~any(boots==boot),"Duplicate physical trial cannot multiply replay data");
    hashes(end+1,1)=hash; boots(end+1,1)=boot; %#ok<AGROW>
    candidateLines = splitlines(strtrim(fileread(fullfile(auditDir,"experience-candidates.jsonl"))));
    candidates = cellfun(@jsondecode,cellstr(candidateLines),UniformOutput=false);
    candidates = candidates(cellfun(@(r)r.stage_confirmed_from_raw_edges,candidates));
    assert(~isempty(candidates),"No directly stage-confirmed action windows");
    for index = 1:numel(candidates)
        r = candidates{index};
        assert(~r.learner_eligible,"Ordinary live admission must not be silently changed");
        if index>1
            previous = candidates{index-1};
            assert(r.t_state_us==previous.t_next_us && isequal(r.state,previous.next_state), ...
                "Causal windows do not form an uninterrupted episode");
            assert(r.command_seq>previous.command_seq);
        end
        assert(r.t_state_us<=r.t_apply_us && r.t_apply_us<r.t_next_us);
        assert(numel(r.observation)==10 && numel(r.action_normalized)==2);
        assert(all(isfinite([r.observation(:);r.next_observation(:);r.action_normalized(:);r.reward])));
        assert(all(abs(r.action_normalized)<=1+1e-6) && r.max_frame_gap_ms<=40);
        % Normal STOP is a time limit, not a terminal physical fault. Keep the
        % verified last active endpoint and bootstrap (IsDone=0).
        r.truncated=index==numel(candidates); r.terminated=false;
        r.shadow_learner_eligible=true;
        r.ordinary_live_learner_eligible=false;
        r.run_index=trialIndex; r.step=index-1; r.boot_id=boot;
        r.analysis_mode="experimental-offline-shadow";
        experience = struct('Observation',{{single(r.observation(:))}}, ...
            'Action',{{single(r.action_normalized(:))}},'Reward',double(r.reward), ...
            'NextObservation',{{single(r.next_observation(:))}},'IsDone',0);
        validateExperience(agent.ExperienceBuffer,experience);
        append(agent.ExperienceBuffer,experience);
        rows{end+1,1}=r; %#ok<AGROW>
    end
    auditReports{trialIndex}=audit;
end
% Fixed behavior gathered these windows. No unseen learned action is applied.
warmup = 128;
trainingPerformed = agent.ExperienceBuffer.Length>=warmup;
trainingStats=[];
predictionsBefore=zeros(numel(rows),2);predictionsAfter=predictionsBefore;
for index=1:numel(rows)
    prediction=getAction(getActor(agent),{single(rows{index}.observation(:))});
    predictionsBefore(index,:)=double(prediction{1}(:)).';
end
if trainingPerformed
    options=rlTrainingFromDataOptions('MaxEpochs',1,'NumStepsPerEpoch',20, ...
        'Plots','none','Verbose',false,'SaveAgentCriteria','none');
    trainingStats=trainFromData(agent,options); %#ok<NASGU>
end
final=getModel(getActor(agent)); delta=0;
for index=1:height(initialValues)
    delta=delta+sum(double(extractdata(final.Learnables.Value{index}-initialValues.Value{index})).^2,'all');
end
criticDelta=zeros(1,2); criticsFinal=getCritic(agent);
for k=1:2
    network=getModel(criticsFinal(k)); values=criticValues{k};
    for index=1:height(values)
        criticDelta(k)=criticDelta(k)+sum(double(extractdata(network.Learnables.Value{index}-values.Value{index})).^2,'all');
    end
end
for index=1:numel(rows)
    prediction=getAction(getActor(agent),{single(rows{index}.observation(:))});
    predictionsAfter(index,:)=double(prediction{1}(:)).';
end
datasetText="";
for index=1:numel(rows), datasetText=datasetText+string(jsonencode(rows{index}))+newline; end
writeUTF8(fullfile(outputDir,"shadow-transitions.jsonl"),datasetText);
actions=cell2mat(cellfun(@(r)reshape(r.action_normalized,1,2),rows,UniformOutput=false));
report=struct(schema_version=1,source="real_motor",simulation_only=false, ...
    mode="experimental-offline-shadow",hardware_accessed=false, ...
    matlab_release=string(version("-release")),physical_trials=numel(runDirs), ...
    replay_experiences=agent.ExperienceBuffer.Length,replay_warmup_required=warmup, ...
    td3_training_performed=trainingPerformed,actor_weight_change_l2=sqrt(delta), ...
    critic_weight_change_l2=sqrt(criticDelta), ...
    requested_training_steps=20*double(trainingPerformed), ...
    actual_training_steps=actualSteps(trainingStats), ...
    shadow_prediction_action_min=min(predictionsAfter,[],1), ...
    shadow_prediction_action_max=max(predictionsAfter,[],1), ...
    unique_normalized_actions=size(unique(actions,"rows"),1), ...
    ki_exploration_performed=any(actions(:,2)~=0), ...
    deployment_allowed=false,live_candidate_auto_applied=false,actor_deployed=false, ...
    ordinary_live_admission=false,thermal_gate_modified=false, ...
    temperature_c=NaN,current_conversion_independently_calibrated=false, ...
    telemetry_sha256=hashes,boot_ids=boots,dataset_sha256=string(sha256(datasetText)), ...
    hash_convention="UTF-8 with LF line endings; field content unchanged", ...
    state_fields=auditReports{1}.state_fields,state_scale=auditReports{1}.state_scale, ...
    note="Only fixed-behavior experimental data; missing ordinary safety admission and Ki action coverage. No performance superiority or deployment claim.");
name="replay-pending.mat";
if trainingPerformed, name="experimental-candidate.mat"; end
save(fullfile(outputDir,name),'agent','report','auditReports','trainingStats');
predictions=table((1:numel(rows))',predictionsBefore(:,1),predictionsBefore(:,2), ...
    predictionsAfter(:,1),predictionsAfter(:,2), ...
    VariableNames={'row','initial_kp_action','initial_ki_action','candidate_kp_action','candidate_ki_action'});
writetable(predictions,fullfile(outputDir,'shadow-predictions.csv'));
writeUTF8(fullfile(outputDir,"training-summary.json"),string(jsonencode(report,PrettyPrint=true))+newline);
end

function steps=actualSteps(stats)
steps=0;
if ~isempty(stats), steps=double(stats.TotalSteps); end
end

function value=sha256(text)
digest=java.security.MessageDigest.getInstance('SHA-256');
digest.update(unicode2native(char(text),'UTF-8'));
bytes=typecast(digest.digest(),'uint8');
value=lower(reshape(dec2hex(bytes,2).',1,[]));
end

function writeUTF8(path,text)
fid=fopen(path,'wb');assert(fid>=0);
closer=onCleanup(@() fclose(fid)); %#ok<NASGU>
fwrite(fid,unicode2native(char(text),'UTF-8'),'uint8');
end
