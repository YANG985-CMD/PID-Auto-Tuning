function [components,proof,sourceElapsedMs]=motorFactualResponseComponents(rows,contract,replaySummary)
% Verified factual reward components; this does not change learning rewards.
manifest=jsondecode(fileread(replaySummary));assert(manifest.passed);
assert(isempty(intersect(contract.training_boot_ids,contract.validation_boot_ids)));
keys=string(cellfun(@(r)char(r.physical_key),rows,UniformOutput=false));
assert(numel(unique(keys))==numel(keys));
components=zeros(4,numel(rows));seen=false(size(keys));maximumError=0;
sourceElapsedMs=zeros(numel(rows),1);
assert(numel(manifest.input_manifest)==numel(rows));
for item=manifest.input_manifest(:)'
    assert(motorFileSHA256(item.file)==string(item.sha256));
    w=jsondecode(fileread(item.file));index=find(keys==string(item.physical_key));
    assert(isscalar(index) && ~seen(index));seen(index)=true;r=rows{index};
    assert(string(w.physical_key)==string(r.physical_key) && string(w.boot_id)==string(r.boot_id));
    if any(string(r.boot_id)==contract.training_boot_ids),expectedSplit="train";else
        assert(any(string(r.boot_id)==contract.validation_boot_ids));expectedSplit="validation";
    end
    assert(string(item.split)==expectedSplit);
    assert(w.state.kp==r.actual_source_kp && w.action_applied(1)==r.actual_target_kp);
    assert(w.state.speed_ref==r.actual_reference_rpm && w.measured_reward_span_us==r.measured_reward_span_us);
    assert(abs(w.time_scaled_reward-r.reward)<1e-12);
    sourceElapsedMs(index)=w.state.elapsed_ms;
    h=w.full_hall_reward;
    assert(isfinite(h.mse_rpm2) && h.mse_rpm2>=0 && isfinite(h.peak_nominal_current_a) && h.peak_nominal_current_a>=0);
    assert(isfinite(h.peak_speed_rpm) && h.peak_speed_rpm>=0 && h.saturation_fraction>=0 && h.saturation_fraction<=1);
    components(:,index)=[h.mse_rpm2/1e6;.3*(h.peak_nominal_current_a/2)^2; ...
        .25*max(0,(h.peak_speed_rpm-1500)/300)^2;.25*h.saturation_fraction];
    assert(contract.physical_single_step_limit(1)==.00027112);
    delta=(r.actual_target_kp-r.actual_source_kp)/.00027112;
    original=-(r.reward+.0005*delta^2)/(r.measured_reward_span_us/100000);
    maximumError=max(maximumError,abs(sum(components(:,index))-original));
end
assert(all(seen) && all(isfinite(components),'all') && maximumError<1e-12);
proof=struct(passed=true,unique_windows=numel(rows),maximum_component_sum_error=maximumError, ...
    replay_summary_sha256=motorFileSHA256(replaySummary), ...
    component_names=["raw-Hall-speed-MSE","nominal-peak-current-square","overspeed","saturation"], ...
    training_reward_changed=false,hardware_accessed=false);
end
