function result=validateSpeedLoopResponseReplay(dataset,actionMask)
% Validate held-gain real-data replay, independently of the publisher.
arguments
    dataset (1,1) string
    actionMask (2,1) double = [1;1]
end
summary=jsondecode(fileread(fullfile(dataset,'window-summary.json')));
file=fullfile(dataset,'response-windows.jsonl');
assert(string(summary.dataset_sha256)==motorFileSHA256(file),'MotorTD3:Hash','Dataset hash mismatch');
items=splitlines(strtrim(fileread(file)));
rows=cellfun(@jsondecode,cellstr(items),UniformOutput=false);
assert(numel(rows)==summary.response_windows);
historyAudit=struct;
if isfield(summary,'history_depth_packets')
    historyAudit=validateMotorHistoryReplay(rows,summary);
end
seenCommands=strings(0,1); seenResponses=strings(0,1);
for k=1:numel(rows)
    r=rows{k};
    assert(string(r.source)=="real_motor" && any(string(r.firmware_id)== ...
        ["g431-speedloop-pi-motion-v5","g431-speedloop-pi-response-8s-v7", ...
         "g431-speedloop-pi-handover-excitation-8s-v11","g431-speedloop-pi-excitation-evidence-8s-v12"]));
    if string(r.firmware_id)~="g431-speedloop-pi-motion-v5"
        assert(r.state(9)==double(single(.00144)) && r.next_state(9)==double(single(.00144)) && ...
            r.action_applied(2)==double(single(.00144)) && r.action_normalized(2)==0);
        assert(r.state(10)>=3900 && r.next_state(10)<8000);
    end
    if any(string(r.firmware_id)==["g431-speedloop-pi-handover-excitation-8s-v11", ...
            "g431-speedloop-pi-excitation-evidence-8s-v12"])
        assert(string(summary.environment_control_family)=="v10-handover-v8-excitation");
        assert(string(r.environment_control_family)==string(summary.environment_control_family));
        assert(isequal(summary.reference_schedule_ms_rpm,[0 1000;4000 1100;5200 900;6400 1000]));
        assert(numel(r.reference_response_schedule)==r.response_sample_count);
        refs=r.reference_response_schedule;
        assert(isequal([refs.telemetry_seq]',r.response_telemetry_seqs(:)));
        for q=1:numel(refs)
            t=refs(q).elapsed_ms;
            expected=1000;
            if t>=4000 && t<5200,expected=1100;
            elseif t>=5200 && t<6400,expected=900;end
            nearBoundary=any(abs(t-[4000 5200 6400])<=2);
            assert(ismember(refs(q).speed_ref,[900 1000 1100]) && ...
                (refs(q).speed_ref==expected || nearBoundary));
        end
    end
    assert(r.stage_confirmed_from_raw_edges && ~r.learner_eligible && ~r.deployment_allowed);
    assert(r.response_sample_count>=summary.minimum_response_samples);
    assert(numel(r.response_telemetry_seqs)==r.response_sample_count);
    assert(r.observed_response_span_ms>=summary.minimum_observed_span_ms);
    assert(r.t_state_us<=r.t_effective_us && r.t_effective_us<r.t_next_us);
    assert(r.t_state_us<=r.t_apply_us && r.t_apply_us<r.t_next_us && r.max_frame_gap_ms<=40);
    assert(numel(r.observation)==10 && numel(r.next_observation)==10);
    assert(all(isfinite([r.observation(:);r.next_observation(:);r.action_normalized(:);r.reward])));
    scales=[1000;1000;1000;1000;3;2;24;.003389;.00144;3000];
    assert(all(abs(r.observation(:)-max(-5,min(5,r.state(:)./scales)))<1e-10));
    assert(all(abs(r.next_observation(:)-max(-5,min(5,r.next_state(:)./scales)))<1e-10));
    actual=(r.action_applied(:)-r.state(8:9))./[.00027112;.000144];
    assert(all(abs(actual-r.action_normalized(:))<1e-8));
    assert(r.validation_split==ismember(r.run_index,summary.validation_run_indices));
    assert(r.discount_factor==.99 && summary.variable_duration_native_training_admitted);
    motorTD3MaskedAction(r.action_normalized(:),actionMask);
    if string(r.action_effect_kind)=="already_confirmed_hold"
        assert(all(abs(r.action_normalized)<1e-7));
        assert(isequal(r.state(8:9),r.action_applied(:)));
        assert(r.t_effective_us==r.t_state_us);
    else
        assert(string(r.action_effect_kind)=="new_gain_applied" && r.t_effective_us==r.t_apply_us);
    end
    commands=string(r.boot_id)+":"+string(r.source_command_seqs(:));
    responses=string(r.boot_id)+":"+string(r.response_telemetry_seqs(:));
    assert(~any(ismember(commands,seenCommands)) && numel(unique(commands))==numel(commands));
    assert(~any(ismember(responses,seenResponses)) && numel(unique(responses))==numel(responses));
    seenCommands=[seenCommands;commands]; seenResponses=[seenResponses;responses]; %#ok<AGROW>
end
split=cellfun(@(r)r.validation_split,rows);
train=rows(~split); validation=rows(split);
trainBoot=unique(cellfun(@(r)string(r.boot_id),train));
validationBoot=unique(cellfun(@(r)string(r.boot_id),validation));
assert(isempty(intersect(trainBoot,validationBoot)));
assert(numel(train)==summary.training_windows && numel(validation)==summary.validation_windows);
actions=cell2mat(cellfun(@(r)r.action_normalized(:),train,UniformOutput=false)');
coverage=struct(positive=sum(actions>1e-7,2)',negative=sum(actions<-1e-7,2)',zero=sum(abs(actions)<=1e-7,2)');
coverageReady=actionMask(2)==0 || (coverage.positive(2)>0 && coverage.negative(2)>0);
ready=numel(train)>=128 && ~isempty(validation) && coverageReady;
result=struct(rows={rows},train={train},validation={validation},summary=summary,history_audit=historyAudit, ...
    training_ready=ready,training_action_coverage=coverage, ...
    remaining_training_windows=max(0,128-numel(train)),deployment_allowed=false);
end
