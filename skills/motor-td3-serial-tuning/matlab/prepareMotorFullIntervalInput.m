function report=prepareMotorFullIntervalInput(input,auditFolder,output)
% Independent MATLAB verification of observed source-to-next-state costs.
arguments
    input (1,1) string
    auditFolder (1,1) string
    output (1,1) string
end
assert(~isfile(output));original=load(input);assert(original.fullHallAudit.passed);
summary=jsondecode(fileread(fullfile(auditFolder,'summary.json')));
rowsPath=fullfile(auditFolder,'full-interval-windows.jsonl');
assert(summary.passed && summary.all_prefix_packets_and_actual_gains_verified);
assert(motorFileSHA256(rowsPath)==string(summary.full_interval_rows_sha256));
fullHallTrain=original.fullHallTrain;fullHallValidation=original.fullHallValidation;
keys=string(cellfun(@(r)char(r.physical_key),[fullHallTrain;fullHallValidation],UniformOutput=false));
assert(numel(unique(keys))==numel(keys) && summary.unique_windows==numel(keys));
seen=false(size(keys));eventsCache=containers.Map('KeyType','char','ValueType','any');
hallCache=containers.Map('KeyType','char','ValueType','any');lines=readlines(rowsPath);
for line=lines'
    if strlength(line)==0,continue;end
    r=jsondecode(line);index=find(keys==string(r.physical_key));assert(isscalar(index) && ~seen(index));seen(index)=true;
    assert(motorFileSHA256(r.source_window_file)==string(r.source_window_sha256));
    assert(motorFileSHA256(r.raw_window_file)==string(r.raw_window_sha256));w=jsondecode(fileread(r.source_window_file));
    assert(string(w.physical_key)==string(r.physical_key) && w.duration_us==r.decision_duration_us);
    folder=fileparts(fileparts(r.raw_window_file));eventPath=fullfile(folder,'stream','events.jsonl');
    if ~isKey(eventsCache,eventPath)
        assert(motorFileSHA256(eventPath)==string(r.source_events_sha256));
        packets=cell(0,1);proofs=cell(0,1);commands=cell(0,1);
        for eventLine=readlines(eventPath)'
            if strlength(eventLine)==0,continue;end
            e=jsondecode(eventLine);
            if string(e.kind)=="telemetry",packets{e.packet.seq}=e.packet;proofs{e.packet.seq}=e.stage_proof;
            elseif string(e.kind)=="command" && string(e.command.type)=="gains",commands{e.command.command_seq}=e.command;end
        end
        eventsCache(eventPath)=struct(packets={packets},proofs={proofs},commands={commands});
    end
    cached=eventsCache(eventPath);p=r.packets(:);proof=r.stage_proofs(:);
    assert(numel(p)==p(end).seq-p(1).seq+1 && isequal(p(1),w.state));
    assert(isequal(p(end-numel(w.response)+1:end),w.response(:)));
    assert(all(diff([p.t_us])>=15000 & diff([p.t_us])<=25000));
    for k=1:numel(p)
        t=p(k);assert(isequal(t,cached.packets{t.seq}) && isequal(proof(k),cached.proofs{t.seq}));
        q=proof(k);c=cached.commands{t.applied_seq};
        assert(t.enabled && t.fault==0 && t.ki==w.action_applied(2));
        assert(any(t.kp==[w.state.kp w.action_applied(1)]) && t.speed_ref==w.full_hall_reward.reference_rpm);
        assert(isfinite(t.speed) && abs(t.speed)<1800 && isfinite(t.current) && t.current>=0 && t.current<2);
        assert(isfinite(t.vbus) && t.vbus>=18 && t.vbus<=30);
        assert(q.started==1 && q.run_seen==1 && q.fault==0 && q.irq_fault==0);
        assert(q.started_us<=q.run_started_us && q.run_started_us<=t.t_us && t.t_us<=q.last_us);
        assert(abs((t.t_us-q.started_us)/1000-t.elapsed_ms)<=2);
        assert(c.kp==t.kp && c.ki==t.ki && c.source_t_us<=t.t_apply_us && t.t_apply_us<=c.expires_us);
        assert(t.t_apply_us<=t.t_us+2);
    end
    lo=p(1).t_us;hi=p(end).t_us;h=r.full_hall_interval;assert(lo==h.begin_us && hi==h.end_us && hi-lo==w.duration_us);
    firstApply=lo;
    if w.state.kp~=w.action_applied(1)
        first=find([p.kp]==w.action_applied(1),1);assert(~isempty(first) && p(first).applied_seq>=w.first_command_seq);
        firstApply=p(first).t_apply_us;
    end
    assert(r.measured_first_new_gain_apply_us==firstApply && r.measured_before_new_gain_us==max(0,firstApply-lo));
    assert(r.omitted_prefix_us==w.response(1).t_us-lo);
    hallPath=fullfile(folder,'full-hall-audit','full-hall-edges.json');
    if ~isKey(hallCache,hallPath)
        assert(motorFileSHA256(hallPath)==string(r.source_full_hall_sha256));hallCache(hallPath)=jsondecode(fileread(hallPath));
    end
    actual=hallCache(hallPath);trace=h.records(:);assert(isequal(actual.records([trace.edge]),trace));
    integral=0;duration=0;peak=0;ref=w.full_hall_reward.reference_rpm;
    for k=1:numel(trace)-1
        a=trace(k);b=trace(k+1);assert(a.valid && a.model_stage==4 && b.edge==a.edge+1 && b.t_us-a.t_us==b.period_us);
        width=max(0,min(hi,b.t_us)-max(lo,a.t_us));duration=duration+width;integral=integral+width*(a.rpm-ref)^2;
        if width>0,peak=max(peak,abs(a.rpm));end
    end
    assert(duration==hi-lo && abs(integral/duration-h.mse_rpm2)<1e-7 && peak==h.peak_speed_rpm);
    current=max([p.current]);sat=trapz([p.t_us],double([p.current]>=1.98))/(hi-lo);
    assert(current==r.full_interval_peak_nominal_current_a && abs(sat-r.full_interval_saturation_fraction)<1e-12);
    reward=(-integral/duration/1e6-.3*(current/2)^2-.25*max(0,(peak-1500)/300)^2-.25*sat)*duration/100000-.0005*w.physical_delta_action(1)^2;
    assert(abs(reward-r.full_decision_reward)<1e-12);
    if index<=numel(fullHallTrain)
        old=fullHallTrain{index};assert(string(r.split)=="train");
        fullHallTrain{index}=replace(old,r,reward);
    else
        j=index-numel(fullHallTrain);old=fullHallValidation{j};assert(string(r.split)=="validation");
        fullHallValidation{j}=replace(old,r,reward);
    end
end
assert(all(seen));fullHallContract=original.fullHallContract;fullHallAudit=original.fullHallAudit;
fullHallContract.learning_reward_profile="full-decision-observed-latency-v1";
fullHallContract.original_physical_rewards_unchanged=false;fullHallContract.raw_recorded_rewards_unchanged=true;
fullHallContract.post_ack_reward_retained=true;fullHallContract.full_interval_rows_sha256=motorFileSHA256(rowsPath);
fullHallContract.prefix_gain_attribution="Observed old/new gain applications retained; prefix is part of delayed-action transition, not all new-gain response";
fullHallAudit.full_interval_independent_checks=numel(keys);fullHallAudit.training_performed=false;
report=struct(passed=true,unique_windows=numel(keys),training_windows=numel(fullHallTrain),validation_windows=numel(fullHallValidation), ...
    source_input_sha256=motorFileSHA256(input),full_interval_rows_sha256=motorFileSHA256(rowsPath), ...
    all_actual_states_actions_next_states_preserved=true,normalization_and_boot_split_preserved=true, ...
    alternate_training_reward_definition=true,original_post_ack_rewards_retained=true,raw_recorded_rewards_unchanged=true, ...
    hardware_accessed=false,training_performed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
save(output,'fullHallTrain','fullHallValidation','fullHallContract','fullHallAudit','report');disp(jsonencode(report));
end
function row=replace(old,r,reward)
assert(abs(old.reward-r.original_post_ack_reward)<1e-12 && old.duration_us==r.decision_duration_us);
assert(old.actual_source_kp==r.actual_source_kp && old.actual_target_kp==r.actual_target_kp);
row=old;row.post_ack_reward=old.reward;row.reward=reward;
row.learning_reward_profile="full-decision-observed-latency-v1";
end
