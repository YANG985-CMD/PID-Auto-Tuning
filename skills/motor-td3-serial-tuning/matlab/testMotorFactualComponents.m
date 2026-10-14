function report=testMotorFactualComponents(input,replaySummary,independentProof,output)
% Component identity against existing independently verified physical costs.
assert(~isfile(output));s=load(input);rows=[s.fullHallTrain;s.fullHallValidation];
[values,proof]=motorFactualResponseComponents(rows,s.fullHallContract,replaySummary);
previous=jsondecode(fileread(independentProof));assert(previous.passed);
keys=string({previous.rows.physical_key});err=0;
for k=1:numel(rows)
    index=find(keys==string(rows{k}.physical_key));assert(isscalar(index));
    err=max(err,abs(sum(values(:,k))-previous.rows(index).cost));
end
assert(err<1e-12);
rejected=0;
for field=["reward","actual_target_kp","actual_reference_rpm"]
    bad=rows;bad{1}.(field)=bad{1}.(field)+.01;
    try
        motorFactualResponseComponents(bad,s.fullHallContract,replaySummary);
    catch e
        assert(string(e.identifier)=="MATLAB:assertion:failed");rejected=rejected+1;
    end
end
assert(rejected==3);
report=struct(passed=true,independently_verified_windows=numel(rows), ...
    maximum_error_vs_existing_Python_cost_proof=err,mismatched_rows_rejected=rejected, ...
    component_proof=proof,TD3_gradient_updates=0,hardware_accessed=false, ...
    training_rewards_changed=false,deployment_allowed=false);
f=fopen(output,'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
