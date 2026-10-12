function report=replaySpeedLoopResponseSuggestions(batch,modelFolder,output)
% Post-training replay suggestions on proven RunStage snapshots, no writeback.
arguments
    batch (1,1) string
    modelFolder (1,1) string
    output (1,1) string
end
folders=dir(fullfile(batch,'round-*'));
rows=table;
for seed=[7,17,27]
    checkpoint=fullfile(modelFolder,"response-candidate-seed-"+seed+".mat");
    loaded=load(checkpoint,'agent');
    actor=getActor(loaded.agent); checkpointHash=motorFileSHA256(checkpoint);
    for k=1:numel(folders)
        folder=fullfile(batch,folders(k).name);
        s=jsondecode(fileread(fullfile(folder,'analysis.json')));
        T=readtable(fullfile(folder,'telemetry.csv'));
        T=T(T.enabled==1 & T.t_us>=s.raw_stage_proof_t_us(1) & T.t_us<=s.raw_stage_proof_t_us(2),:);
        state=[T.speed_ref,T.speed,T.speed_ref-T.speed,T.error_history,T.integral_output, ...
            T.current,T.vbus,T.kp,T.ki,T.elapsed_ms];
        obs=max(-5,min(5,state./[1000,1000,1000,1000,3,2,24,.003389,.00144,3000]));
        a=getAction(actor,{single(obs')}); predictions=reshape(double(a{1}),2,[])';
        assert(all(isfinite(predictions),'all') && all(abs(predictions)<=1,'all'));
        candidate=max([.0013556,.00072],min([.0054224,.00216], ...
            [T.kp,T.ki]+predictions.*[.00027112,.000144]));
        suggestions=table(repmat(seed,height(T),1),repmat(k,height(T),1), ...
            T.seq,T.t_us,T.kp,T.ki,predictions(:,1),predictions(:,2), ...
            candidate(:,1),candidate(:,2), ...
            repmat(checkpointHash,height(T),1),false(height(T),1), ...
            VariableNames={'seed','round','telemetry_seq','t_us','actual_kp','actual_ki', ...
            'actor_kp_action','actor_ki_action','candidate_kp','candidate_ki', ...
            'checkpoint_sha256','hardware_writeback'});
        rows=[rows;suggestions]; %#ok<AGROW>
    end
end
writetable(rows,output);
report=struct(rows=height(rows),prediction_mode="post_training_offline_replay", ...
    during_physical_collection=false,hardware_accessed=false,hardware_writeback=false, ...
    performance_verified=false,deployment_allowed=false);
end
