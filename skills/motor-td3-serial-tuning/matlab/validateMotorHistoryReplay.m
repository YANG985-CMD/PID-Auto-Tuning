function report=validateMotorHistoryReplay(rows,summary)
% Independently derive history and bounded task endpoint from hashed telemetry.
assert(summary.history_depth_packets==2 && summary.physical_fields_and_flags_preserved);
manifest=summary.input_file_manifest;
rawByBoot=containers.Map('KeyType','char','ValueType','any');
for k=1:numel(manifest)
    path=string(manifest(k).path);
    assert(string(manifest(k).sha256)==motorFileSHA256(path),"MotorTD3:RawHash","Physical source changed");
    if endsWith(path,"telemetry.jsonl")
        text=splitlines(strtrim(fileread(path)));
        data=cellfun(@jsondecode,cellstr(text),UniformOutput=false);
        packets=vertcat(data{:});boot=char(string(packets(1).boot_id));
        assert(~isKey(rawByBoot,boot));rawByBoot(boot)=packets;
    end
end
for k=1:numel(rows)
    r=rows{k};raw=rawByBoot(char(string(r.boot_id)));
    [source,sourceProof]=derive(raw,r.t_state_us);
    [next,nextProof]=derive(raw,r.t_next_us);
    assert(isequal(source,r.history_observation(:)) && isequal(next,r.history_next_observation(:)));
    assert(isequal(sourceProof,r.history_source_proof) && isequal(nextProof,r.history_next_proof));
    if ~r.learning_is_done
        assert(r.learning_reward==r.reward && isequal(r.learning_next_observation,r.next_observation));
        assert(isequal(r.learning_history_next_observation,r.history_next_observation));
    else
        assert(r.truncated && ~r.terminated);
        active=raw([raw.enabled]);last=active(end);
        stopped=raw(find([raw.seq]>last.seq & ~[raw.enabled],1));
        proof=r.bounded_terminal_evidence;
        assert(last.seq==proof.last_active_seq && last.t_us==proof.last_active_t_us);
        assert(stopped.seq==proof.stop_seq && stopped.t_us==proof.stop_t_us && stopped.fault==0);
        assert(proof.stop_acknowledged && proof.outputs_off && proof.core_halted && proof.can_released);
        assert(stopped.t_us>last.t_us && stopped.t_us-last.t_us<=40000);
        assert(all([raw.fault]==0));
        tail=raw([raw.t_us]>r.t_effective_us & [raw.t_us]<=last.t_us);
        assert(all([tail.enabled]) && all([tail.kp]==r.action_applied(1) & [tail.ki]==r.action_applied(2)));
        assert(isequal([tail.seq]',r.bounded_response_telemetry_seqs(:)));
        t=double([tail.t_us]);err=([tail.speed_ref]-[tail.speed]).^2;
        mse=trapz(t,err)/(t(end)-t(1));current=max(abs([tail.current]));speed=max(abs([tail.speed]));
        sat=trapz(t,double(abs([tail.current])>=1.98))/(t(end)-t(1));
        reward=-mse/1e6-.12*(current/2)^2-.08*max(0,(speed-1500)/300)^2-.10*sat-.005*sum(r.action_normalized.^2);
        assert(abs(reward-r.learning_reward)<1e-12);
        [final,finalProof]=derive(raw,last.t_us);
        assert(isequal(final,r.learning_history_next_observation(:)) && isequal(finalProof,r.bounded_history_next_proof));
    end
end
boots=unique(cellfun(@(r)string(r.boot_id),rows));
for b=boots(:)'
    indices=find(cellfun(@(r)string(r.boot_id)==b,rows));
    assert(sum(cellfun(@(r)r.learning_is_done,rows(indices)))==1 && rows{indices(end)}.learning_is_done);
    total=0;
    for k=numel(indices):-1:1
        r=rows{indices(k)};total=r.learning_reward+.99*total;
        assert(abs(total-r.logged_bounded_return)<1e-12);
    end
end
report=struct(passed=true,checked_rows=numel(rows),bounded_terminals=numel(boots), ...
    future_history_rejected=true,raw_inputs_hashed=true,physical_flags_preserved=true,hardware_accessed=false);
end

function [observation,proof]=derive(raw,time)
i=find([raw.t_us]==time);assert(isscalar(i) && i>=3);
past=raw(i-2:i);assert(all([past.enabled]) && all([past.fault]==0));
assert(all(diff([past.seq])==1) && all(diff([past.t_us])>=15000 & diff([past.t_us])<=25000));
p=past(3);scales=[1000;1000;1000;1000;3;2;24;.003389;.00144;3000];
state=[p.speed_ref;p.speed;p.speed_ref-p.speed;p.error_history;p.integral_output;p.current;p.vbus;p.kp;p.ki;p.elapsed_ms];
observation=state./scales;
observation(4)=(past(2).speed_ref-past(2).speed)/1000;
observation(9)=(past(1).speed_ref-past(1).speed)/1000;
observation=max(-5,min(5,observation));
proof=struct(source_seq=p.seq,past_sequences=[past(1:2).seq]', ...
    past_t_us=[past(1:2).t_us]',past_errors_rpm=([past(1:2).speed_ref]-[past(1:2).speed])');
end
