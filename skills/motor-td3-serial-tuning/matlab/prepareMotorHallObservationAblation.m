function report=prepareMotorHallObservationAblation(originalInput,viewPath,output)
% Alternate causal observations on identical actual actions and rewards.
arguments
    originalInput (1,1) string
    viewPath (1,1) string
    output (1,1) string
end
assert(~isfile(output));original=load(originalInput);view=jsondecode(fileread(viewPath));
assert(original.fullHallAudit.passed && view.passed && view.no_future_edges_used);
assert(view.physical_rewards_unchanged && view.physical_actions_unchanged && view.physical_split_unchanged);
assert(view.observation_profile=="causal-six-period-Hall-sector-v1");
assert(view.unique_windows==numel(original.fullHallTrain)+numel(original.fullHallValidation));
trainingFeatures=[];hallSources=containers.Map('KeyType','char','ValueType','any');
origins=containers.Map('KeyType','char','ValueType','double');
for row=view.rows(:)'
    assert(motorFileSHA256(row.original_replay_window)==string(row.original_replay_window_sha256));
    w=jsondecode(fileread(row.original_replay_window));
    if ~isKey(hallSources,row.full_hall_file)
        assert(motorFileSHA256(row.full_hall_file)==string(row.full_hall_sha256));
        hallSources(row.full_hall_file)=jsondecode(fileread(row.full_hall_file));
        lines=readlines(fullfile(fileparts(fileparts(row.full_hall_file)),'trial','telemetry.jsonl'));
        for line=lines'
            if strlength(line)==0,continue;end
            p=jsondecode(line);
            if p.enabled
                assert(p.applied_seq==0 && p.t_apply_us>0);
                origins(row.full_hall_file)=p.t_apply_us;break;
            end
        end
    end
    hall=hallSources(row.full_hall_file);origin=origins(row.full_hall_file);
    for group={'state_proof','next_state_proof'}
        if strcmp(group{1},'state_proof'),history=w.state_history(end-1:end);vector=row.features;
        else,history=w.response(end-1:end);vector=row.next_features;end
        proofs=row.(group{1});speeds=zeros(1,2);
        for proofIndex=1:2
            proof=proofs(proofIndex);p=history(proofIndex);
            assert(proof.packet_seq==p.seq);
            centerTime=origin+p.elapsed_ms*1000;margin=max(2,abs(p.elapsed_ms*1000)*2^-22+1);
            assert(abs(proof.snapshot_lower_us-(centerTime-margin))<1e-7);
            assert(abs(proof.snapshot_upper_us-(centerTime+margin))<1e-7);
            assert(proof.last_used_edge_us<=proof.snapshot_lower_us);
            indices=proof.last_used_edge-5:proof.last_used_edge;six=hall.records(indices);
            assert(all([six.edge]==indices) && all([six.valid]) && all([six.model_stage]==4));
            assert(six(end).t_us==proof.last_used_edge_us && six(end).hall_code==proof.last_used_hall_code);
            assert(isequal([six.period_us],proof.six_completed_periods_us(:)'));
            assert(numel(unique([six.hall_code]))==6 && all([six.t_us]<=proof.snapshot_lower_us));
            assert(proof.last_used_edge==numel(hall.records) || hall.records(proof.last_used_edge+1).t_us>proof.snapshot_lower_us);
            assert(numel(proof.six_completed_periods_us)==6 && all(proof.six_completed_periods_us>0));
            assert(abs(proof.causal_speed_rpm-3e7/sum(proof.six_completed_periods_us))<1e-10);
            speeds(proofIndex)=proof.causal_speed_rpm;
        end
        p=history(end);codeIndex=find([6 2 3 1 5 4]==proofs(end).last_used_hall_code)-1;
        phase=2*pi*codeIndex/6;
        expected=[p.speed_ref/1000 speeds(end)/1000 (p.speed_ref-speeds(end))/1000 ...
            (history(1).speed_ref-speeds(1))/1000 p.integral_output/3 p.current/2 p.vbus/24 ...
            p.kp/.003389 sin(phase) cos(phase)];
        assert(max(abs(expected-vector(:)'))<1e-10);
    end
    if string(row.split)=="train"
        trainingFeatures=[trainingFeatures;row.features(:)';row.next_features(:)']; %#ok<AGROW>
    end
end
center=mean(trainingFeatures,1);
scale=max(std(trainingFeatures,0,1),[.1 .1 .02 .02 .1 .1 .1 .05 .1 .1]);
fullHallContract=original.fullHallContract;
fullHallContract.observation_profile=string(view.observation_profile);
fullHallContract.feature_names=string(view.feature_names(:)');
fullHallContract.state_center=center;fullHallContract.state_scale=scale;
fullHallContract.engineering_state_scale=[1000 1000 1000 1000 3 2 24 .003389 1 1];
fullHallContract.raw_engineering_state_scale=fullHallContract.engineering_state_scale;
fullHallContract.actor_input_mask=ones(1,10);fullHallContract.critic_input_mask=ones(1,10);
fullHallContract.actor_elapsed_time_masked=true;fullHallContract.runtime_compatible=false;
fullHallContract.elapsed_feature_present=false;
fullHallContract.normalization_source="Training boots only; causal six-period speed and sector features";
fullHallContract.observation_view_sha256=motorFileSHA256(viewPath);
fullHallTrain=replace(original.fullHallTrain,"train");fullHallValidation=replace(original.fullHallValidation,"validation");
fullHallAudit=original.fullHallAudit;
fullHallAudit.observation_profile=fullHallContract.observation_profile;
fullHallAudit.causal_observation_checks=4*view.unique_windows;
report=struct(passed=true,unique_windows=view.unique_windows,training_windows=numel(fullHallTrain), ...
    validation_windows=numel(fullHallValidation),action_mask=[1 0], ...
    feature_names=fullHallContract.feature_names,source_input_sha256=motorFileSHA256(originalInput), ...
    observation_view_sha256=fullHallContract.observation_view_sha256, ...
    training_only_normalization=true,physical_rewards_unchanged=true,physical_actions_unchanged=true, ...
    no_future_edges_used=true,hardware_accessed=false,training_performed=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
save(output,'fullHallAudit','fullHallContract','fullHallTrain','fullHallValidation','report');
disp(jsonencode(report));

    function result=replace(rows,split)
        selected=view.rows(string({view.rows.split})==split);result=rows;
        assert(numel(selected)==numel(rows));
        for index=1:numel(rows)
            assert(string(rows{index}.physical_key)==string(selected(index).physical_key));
            assert(string(rows{index}.boot_id)==string(selected(index).boot_id));
            before=rows{index};after=before;
            after.observation=single(max(-5,min(5,(selected(index).features(:)-center')./scale')));
            after.next_observation=single(max(-5,min(5,(selected(index).next_features(:)-center')./scale')));
            assert(isequaln(rmfield(before,{'observation','next_observation'}),rmfield(after,{'observation','next_observation'})));
            result{index}=after;
        end
    end
end
