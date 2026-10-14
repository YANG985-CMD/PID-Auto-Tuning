function [report,contract,train,validation]=auditMotorFullHallReplay(replay,oldCheckpoint)
% Independently verify actual actions and integrate every causal Hall interval.
arguments
    replay (1,1) string
    oldCheckpoint (1,1) string
end
source=jsondecode(fileread(fullfile(replay,'summary.json')));
assert(source.passed && ~source.old_replay_appended && source.total_unique_windows>=256);
referenceExcited=isfield(source,'reference_data_revision');
if referenceExcited
    assert(any(string(source.reference_data_revision)==["reference-excited-local4-capture-v1","reference-excited-upper8-dense-capture-v1","reference-excited-bidirectional16-upper8-capture-v1"]));
    assert(source.reference_crossing_windows_rejected && isequal(source.references_allowed_rpm(:)',[950 1000 1050]));
end
version=string(source.action_coordinate_version);
assert(any(version==["absolute-target-lower16-scale0p00054224-v1","absolute-target-lower16-upper4-scale0p00054224-v2","absolute-target-switching-local4-scale0p00054224-v3","absolute-target-upper8-scale0p00054224-v4","absolute-target-upper8-dense-scale0p00054224-v5","absolute-target-upper8-dense-reference-scale0p00054224-v6","absolute-target-bidirectional16-upper8-scale0p00054224-v7"]));
if version=="absolute-target-bidirectional16-upper8-scale0p00054224-v7"
    assert(referenceExcited && string(source.reference_data_revision)=="reference-excited-bidirectional16-upper8-capture-v1");
    assert(source.dynamic_excitation_present_in_both_splits && source.host_single_kp_step_limit==.00013556);
    assert(source.old_large_steps_explicitly_rejected_not_clipped && ~source.current_v26_continuous_negative_runtime_compatible);
    assert(motorFileSHA256(source.semantic_review_file)==string(source.semantic_review_sha256));
    assert(motorFileSHA256(source.split_review_file)==string(source.split_review_sha256));
    shared=jsondecode(fileread(source.semantic_review_file));splitProof=jsondecode(fileread(source.split_review_file));
    assert(shared.passed && shared.core_FOC_PI_ADC_Hall_and_protection_source_identical && shared.units_and_control_period_source_identical);
    assert(splitProof.passed && isempty(splitProof.assignment_conflicts) && isempty(splitProof.missing_assignments));
elseif version=="absolute-target-upper8-dense-reference-scale0p00054224-v6"
    assert(referenceExcited && string(source.reference_data_revision)=="reference-excited-upper8-dense-capture-v1");
    assert(source.dynamic_excitation_present_in_both_splits, ...
        'MotorTD3:ReferenceCoverage','Need actual v26 reference excitation in both boot splits');
elseif referenceExcited
    assert(version=="absolute-target-switching-local4-scale0p00054224-v3" && string(source.reference_data_revision)=="reference-excited-local4-capture-v1");
end
s=load(oldCheckpoint,'contract');contract=s.contract;
contract.stream_gain_profile="lower16-fullhall";
if version~="absolute-target-lower16-scale0p00054224-v1"
    if version=="absolute-target-bidirectional16-upper8-scale0p00054224-v7"
        contract.stream_gain_profile="bidirectional16-upper8-fullhall";
    elseif any(version==["absolute-target-upper8-dense-scale0p00054224-v5","absolute-target-upper8-dense-reference-scale0p00054224-v6"])
        contract.stream_gain_profile="upper8-dense-fullhall";
    elseif version=="absolute-target-upper8-scale0p00054224-v4"
        contract.stream_gain_profile="upper8-fullhall";
    elseif version=="absolute-target-switching-local4-scale0p00054224-v3"
        contract.stream_gain_profile="switching-local4-fullhall";
    else
        contract.stream_gain_profile="lower16-upper4-fullhall";
    end
    assert(string(source.stream_gain_profile)==contract.stream_gain_profile);
    support=motorStreamGainSpec(contract.stream_gain_profile);
    assert(isequal(source.exact_action_kp_levels(:)',support.exact_kp_levels));
end
contract.gain_step_scale(1)=double(single(.00054224));
contract.encoded_baseline_gains(1)=double(single(.003389));
contract.action_coordinate_version=source.action_coordinate_version;
contract.physical_single_step_limit=[.00027112 .000144];
contract.action_mask=[1 0];contract.runtime_compatible=false;
if version=="absolute-target-bidirectional16-upper8-scale0p00054224-v7"
    contract.execution_mode="bidirectional-continuous-step-clamp";
    contract.execution_mapping_version="bidirectional16-upper8-continuous-relative-step-clamp-v1";
    contract.host_single_kp_step_limit=.00013556;
    contract.execution_wrapper_required=true;
    contract.straight_through_gradient_is_experimental_surrogate=false;
    contract.required_firmware_family="v27-bidirectional";
end
contract.actor_input_mask=[ones(1,9) 0];contract.critic_input_mask=contract.actor_input_mask;
contract.actor_actual_kp_input_masked=false;
if isfield(source,'whole_boot_split')
    ids=string({source.whole_boot_split.boot_id});splits=string({source.whole_boot_split.split});
    contract.training_boot_ids=ids(splits=="train");contract.validation_boot_ids=ids(splits=="validation");
else
    contract.training_boot_ids=string(source.unique_boots{1});contract.validation_boot_ids=string(source.unique_boots{2});
end
assert(isempty(intersect(contract.training_boot_ids,contract.validation_boot_ids)));
contract.training_boot_id=contract.training_boot_ids(1);contract.validation_boot_id=contract.validation_boot_ids(1);
contract.primary_reward_metric="raw-Hall-held-time-integral-v1";
contract.reference_excited_data=referenceExcited;
rawTrain=[];
for item=source.input_manifest(:)'
    assert(motorFileSHA256(item.file)==string(item.sha256));w=jsondecode(fileread(item.file));
    assert(string(w.data_revision)=="complete-Hall-reward-new-action-coordinate-v1");
    if string(item.split)=="train"
        rawTrain=[rawTrain;features(w.state_history);features(w.response(end-2:end))]; %#ok<AGROW>
    end
end
contract.state_center=mean(rawTrain,1);
contract.state_scale=max(std(rawTrain,0,1),[.1 .1 .02 .02 .1 .1 .1 .05 .02 1]);
contract.state_center(10)=0;contract.state_scale(10)=1;
contract.normalization_source="training boots only; actual state and next-state histories";
spec=motorStreamGainSpec(contract.stream_gain_profile);
contract.action_lower_limit=spec.action_lower_limit;contract.action_upper_limit=spec.action_upper_limit;
contract.actor_output_affine_scale=spec.output_scale;contract.actor_output_affine_bias=spec.output_bias;
train={};validation={};keys=strings(0,1);hallSources=containers.Map('KeyType','char','ValueType','any');
for item=source.input_manifest(:)'
    w=jsondecode(fileread(item.file));[e,key]=motorLiveWindowExperience(w,contract);
    assert(string(w.action_coordinate_version)==version);
    assert(~any(keys==key));keys(end+1)=key; %#ok<AGROW>
    assert(string(item.raw_window_sha256)==motorFileSHA256(item.raw_window_file));
    assert(w.duration_us==w.response(end).t_us-w.state.t_us);
    assert(w.measured_reward_span_us==w.response(end).t_us-w.response(1).t_us);
    assert(abs(w.elapsed_discount-.99^(w.duration_us/100000))<1e-12);
    h=w.full_hall_reward;rows=h.records;total=0;mse=0;peak=0;
    ref=1000;
    if referenceExcited
        assert(string(w.reference_data_revision)==string(source.reference_data_revision));
        ref=h.reference_rpm;assert(any(ref==[950 1000 1050]));
        assert(all([w.state_history.speed_ref w.response.speed_ref]==ref));
    else
        assert(~isfield(h,'reference_rpm'));
    end
    hallPath=fullfile(fileparts(fileparts(item.raw_window_file)),'full-hall-audit','full-hall-edges.json');
    if ~isKey(hallSources,hallPath)
        assert(motorFileSHA256(hallPath)==string(h.full_hall_sha256));
        hallSources(hallPath)=jsondecode(fileread(hallPath));
    end
    actualHall=hallSources(hallPath);
    assert(isequal(actualHall.records([rows.edge]),rows(:)));
    assert(h.peak_nominal_current_a==max([w.response.current]));
    responseTimes=[w.response.t_us];
    actualSaturation=trapz(responseTimes,double([w.response.current]>=1.98))/(responseTimes(end)-responseTimes(1));
    assert(abs(h.saturation_fraction-actualSaturation)<1e-12);
    assert(abs(w.physical_delta_action(1))<=1+1e-6 && w.physical_delta_action(2)==0);
    if version=="absolute-target-bidirectional16-upper8-scale0p00054224-v7"
        assert(abs(w.action_applied(1)-w.state.kp)<=.00013556+1e-9);
    end
    for k=1:numel(rows)-1
        assert(rows(k).valid && rows(k).model_stage==4 && rows(k+1).edge==rows(k).edge+1);
        assert(rows(k+1).t_us-rows(k).t_us==rows(k+1).period_us);
        width=max(0,min(h.end_us,rows(k+1).t_us)-max(h.begin_us,rows(k).t_us));
        total=total+width;mse=mse+width*(rows(k).rpm-ref)^2;
        if width>0,peak=max(peak,abs(rows(k).rpm));end
    end
    mse=mse/total;assert(total==w.measured_reward_span_us && abs(mse-h.mse_rpm2)<1e-7);
    assert(abs(peak-h.peak_speed_rpm)<1e-12);
    rate=-mse/1e6-.3*(h.peak_nominal_current_a/2)^2-.25*max(0,(peak-1500)/300)^2-.25*h.saturation_fraction;
    reward=rate*total/100000-.0005*w.physical_delta_action(1)^2;
    assert(abs(reward-w.time_scaled_reward)<1e-12);
    row=struct(observation=double(e.Observation{1}),next_observation=double(e.NextObservation{1}), ...
        action_normalized=double(e.Action{1}),reward=reward,legacy_time_reward=w.legacy_time_scaled_reward, ...
        actual_source_kp=w.state.kp,actual_target_kp=w.action_applied(1), ...
        actual_reference_rpm=ref, ...
        duration_us=w.duration_us,measured_reward_span_us=total,boot_id=string(w.boot_id),physical_key=key);
    if string(item.split)=="train"
        assert(any(string(w.boot_id)==contract.training_boot_ids));train{end+1,1}=row; %#ok<AGROW>
    else
        assert(any(string(w.boot_id)==contract.validation_boot_ids));validation{end+1,1}=row; %#ok<AGROW>
    end
end
assert(numel(train)>=128 && numel(validation)>=128 && numel(unique(keys))==numel(keys));
switchTrain=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,train));
switchValidation=sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,validation));
report=struct(passed=true,unique_train_windows=numel(train),unique_validation_windows=numel(validation), ...
    measured_gain_switch_train_windows=switchTrain,measured_gain_switch_validation_windows=switchValidation, ...
    independent_full_hall_reward_checks=numel(keys),action_mask=[1 0],gain_step_scale=contract.gain_step_scale, ...
    hardware_accessed=false,training_performed=false,normalization_training_boot_only=true, ...
    training_boot_ids=contract.training_boot_ids,validation_boot_ids=contract.validation_boot_ids, ...
    old_replay_appended=false,deployment_allowed=false,performance_claim_allowed=false);
disp(jsonencode(report));
end

function x=features(h)
t=h(end);x=[t.speed_ref t.speed t.speed_ref-t.speed h(end-1).speed_ref-h(end-1).speed ...
    t.integral_output t.current t.vbus t.kp h(end-2).speed_ref-h(end-2).speed t.elapsed_ms];
x=x./[1000 1000 1000 1000 3 2 24 .003389 1000 3000];
x=double(single(max(-5,min(5,x))));
end
