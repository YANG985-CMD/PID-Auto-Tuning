function report=prepareMotorPIOutputInput(originalInput,viewFile,output)
% Replace the unused clock column with the actual last-PI-boundary command.
arguments
    originalInput (1,1) string
    viewFile (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(originalInput);v=jsondecode(fileread(viewFile));
assert(s.fullHallAudit.passed && v.passed && ~v.training_performed);
assert(string(v.observation_profile)=="history20-40-PI-command-v1");
assert(v.physical_actions_unchanged && v.physical_rewards_unchanged && v.physical_split_unchanged);
originalContract=s.fullHallContract;
assert(originalContract.actor_input_mask(10)==0 && originalContract.critic_input_mask(10)==0);
assert(isequal(originalContract.action_mask,[1 0]));
assert(numel(v.rows)==numel(s.fullHallTrain)+numel(s.fullHallValidation));
trainingFeature=[];
for row=v.rows(:)'
    assert(motorFileSHA256(row.original_window_file)==string(row.original_window_sha256));
    w=jsondecode(fileread(row.original_window_file));
    assert(string(w.physical_key)==string(row.physical_key) && string(w.boot_id)==string(row.boot_id));
    assert(string(w.split)==string(row.split) && isequal(w.state,w.state_history(end)));
    p=[w.state,w.response(end)];
    command=double(min(single(3),max(single(-3),single([p.kp]).*single([p.error_history])+single([p.integral_output]))));
    feature=double(single(command/3));
    assert(isequal(command,[row.source_Iq_command_A,row.next_Iq_command_A]));
    assert(isequal(feature,[row.source_feature,row.next_feature]));
    assert(isequal([p.seq],[row.source_packet_seq,row.next_packet_seq]));
    assert(isequal([p.t_us],[row.source_packet_t_us,row.next_packet_t_us]) && p(1).t_us<p(2).t_us);
    if string(row.split)=="train",trainingFeature=[trainingFeature;feature(:)];end %#ok<AGROW>
end
fullHallContract=originalContract;
fullHallContract.observation_profile=string(v.observation_profile);
fullHallContract.feature_names(10)="last_PI_Iq_command";
fullHallContract.state_center(10)=mean(trainingFeature);
fullHallContract.state_scale(10)=max(std(trainingFeature,0),.02);
fullHallContract.actor_input_mask(10)=1;fullHallContract.critic_input_mask(10)=1;
fullHallContract.actor_elapsed_time_masked=true;fullHallContract.elapsed_feature_present=false;
fullHallContract.raw_engineering_state_scale(10)=3;
if isfield(fullHallContract,'engineering_state_scale'),fullHallContract.engineering_state_scale(10)=3;end
fullHallContract.runtime_compatible=false;
fullHallContract.required_observation_builder="last_PI_command_f32 plus original nine history inputs";
fullHallContract.PI_output_is_command_not_measured_current=true;
fullHallContract.observation_view_sha256=motorFileSHA256(viewFile);
fullHallContract.normalization_source="Original training-only columns 1-9; PI command column 10 fit only on training boot state/next-state packets";
fullHallTrain=replace(s.fullHallTrain,"train");fullHallValidation=replace(s.fullHallValidation,"validation");
fullHallAudit=s.fullHallAudit;
fullHallAudit.observation_profile=fullHallContract.observation_profile;
fullHallAudit.PI_output_independent_formula_checks=2*numel(v.rows);
report=struct(passed=true,unique_windows=numel(v.rows),training_windows=numel(fullHallTrain), ...
    validation_windows=numel(fullHallValidation),source_input_sha256=motorFileSHA256(originalInput), ...
    view_sha256=motorFileSHA256(viewFile),observation_profile=fullHallContract.observation_profile, ...
    first_nine_normalized_inputs_unchanged=true,actual_actions_rewards_splits_and_keys_unchanged=true, ...
    feature10_center=fullHallContract.state_center(10),feature10_scale=fullHallContract.state_scale(10), ...
    training_boot_only_normalization=true,PI_output_is_command_not_measured_current=true, ...
    Ki_fixed=.00144,action_mask=[1 0],runtime_compatible=false, ...
    hardware_accessed=false,training_performed=false,candidate_admission=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
save(output,'fullHallAudit','fullHallContract','fullHallTrain','fullHallValidation','report');
disp(jsonencode(report));

    function rows=replace(oldRows,split)
        selected=v.rows(string({v.rows.split})==split);rows=oldRows;
        assert(numel(selected)==numel(oldRows));
        for k=1:numel(oldRows)
            before=oldRows{k};proof=selected(k);after=before;
            assert(string(before.physical_key)==string(proof.physical_key) && string(before.boot_id)==string(proof.boot_id));
            after.observation(10)=single(max(-5,min(5,(proof.source_feature-fullHallContract.state_center(10))/fullHallContract.state_scale(10))));
            after.next_observation(10)=single(max(-5,min(5,(proof.next_feature-fullHallContract.state_center(10))/fullHallContract.state_scale(10))));
            assert(isequal(before.observation(1:9),after.observation(1:9)));
            assert(isequal(before.next_observation(1:9),after.next_observation(1:9)));
            assert(isequaln(rmfield(before,{'observation','next_observation'}),rmfield(after,{'observation','next_observation'})));
            rows{k}=after;
        end
    end
end
