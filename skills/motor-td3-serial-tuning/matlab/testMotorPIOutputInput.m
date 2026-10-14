function report=testMotorPIOutputInput(originalInput,viewFile,input,output)
% Causal source, normalization and malformed-input checks on the real view.
arguments
    originalInput (1,1) string
    viewFile (1,1) string
    input (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);
a=load(originalInput);b=load(input);v=jsondecode(fileread(viewFile));
assert(b.report.passed && numel(v.rows)==1792);
assert(isequal(a.fullHallContract.state_center(1:9),b.fullHallContract.state_center(1:9)));
assert(isequal(a.fullHallContract.state_scale(1:9),b.fullHallContract.state_scale(1:9)));
selected=v.rows(string({v.rows.split})=="train");
actual=[selected.source_feature selected.next_feature];
assert(abs(mean(actual)-b.fullHallContract.state_center(10))<1e-12);
assert(abs(max(std(actual,0),.02)-b.fullHallContract.state_scale(10))<1e-12);
before=[a.fullHallTrain;a.fullHallValidation];after=[b.fullHallTrain;b.fullHallValidation];
for k=1:numel(before)
    assert(isequaln(rmfield(before{k},{'observation','next_observation'}), ...
        rmfield(after{k},{'observation','next_observation'})));
    assert(isequal(before{k}.observation(1:9),after{k}.observation(1:9)));
    assert(isequal(before{k}.next_observation(1:9),after{k}.next_observation(1:9)));
end
c=b.fullHallContract;c.execution_mode="bidirectional-feasible-fraction";
c.actor_raw_coordinates="feasible-fraction[-1,1]";c.critic_action_coordinates="absolute-target-v7";
parts=cellfun(@(r)r.observation(:),after,UniformOutput=false);x=single(cat(2,parts{:}));
parts=cellfun(@(r)r.action_normalized(:),after,UniformOutput=false);action=single(cat(2,parts{:}));
mapped=motorFeasibleFractionAction(motorFeasibleFractionInverse(action,x,c),x,c);
mapError=max(abs(double(mapped(:)-action(:))));assert(mapError<1e-6 && all(mapped(2,:)==0));
mutations=["source-value","next-sequence","source-hash","split-role"];
for name=mutations
    wrong=v;
    switch name
        case "source-value",wrong.rows(1).source_feature=wrong.rows(1).source_feature+.001;
        case "next-sequence",wrong.rows(1).next_packet_seq=wrong.rows(1).source_packet_seq;
        case "source-hash",wrong.rows(1).original_window_sha256=repmat('0',1,64);
        case "split-role",wrong.rows(1).split='validation';
    end
    path=fullfile(output,name+".json");file=fopen(path,'wb');
    fwrite(file,unicode2native(jsonencode(wrong),'UTF-8'));fclose(file);
    target=fullfile(output,name+"-must-not-exist.mat");caught=false;
    try
        prepareMotorPIOutputInput(originalInput,path,target);
    catch
        caught=true;
    end
    assert(caught && ~isfile(target),'MotorTD3:PIViewRejection','Malformed source view must be rejected before saving');
end
report=struct(passed=true,unique_actual_windows=numel(after),physical_actions_rewards_split_and_keys_exact=true, ...
    first_nine_inputs_exact=true,normalization_training_boot_only=true,malformed_views_rejected=4, ...
    replay_execution_roundtrip_max_action_error=mapError,action_mask=[1 0],Ki_fixed=.00144, ...
    hardware_accessed=false,training_performed=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'summary.json'),'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
