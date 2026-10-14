function report=testMotorCausalHallInputs(originalInput,viewPath,cohortPath,output)
% Verify future-edge, sector-feature and retrospective cohort tampering rejection.
arguments
    originalInput (1,1) string
    viewPath (1,1) string
    cohortPath (1,1) string
    output (1,1) string
end
assert(startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
assert(~isfolder(output));mkdir(output);
view=jsondecode(fileread(viewPath));cohort=jsondecode(fileread(cohortPath));rejected=false(1,3);
for k=1:3
    if k<=2
        bad=view;
        if k==1,bad.rows(1).state_proof(1).last_used_edge_us=bad.rows(1).state_proof(1).snapshot_lower_us+1;
        else,bad.rows(1).features(9)=bad.rows(1).features(9)+.1;end
    else
        bad=cohort;bad.eligibility(1).selected_for_matched_steady_cohort=~bad.eligibility(1).selected_for_matched_steady_cohort;
    end
    file=fullfile(output,"tampered-"+k+".json");write(file,bad);target=fullfile(output,"rejected-"+k+".mat");
    try
        if k<=2,prepareMotorHallObservationAblation(originalInput,file,target);
        else,prepareMotorSteadyCohort(originalInput,file,target);end
    catch err
        rejected(k)=strcmp(err.identifier,'MATLAB:assertion:failed');
    end
    assert(rejected(k) && ~isfile(target));
end
report=struct(passed=all(rejected),tests=3,future_edge_rejected=rejected(1), ...
    altered_sector_feature_rejected=rejected(2),altered_plateau_membership_rejected=rejected(3), ...
    hardware_accessed=false,training_performed=false,weights_changed=false);
write(fullfile(output,'summary.json'),report);disp(jsonencode(report));
end

function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value),'UTF-8'));fclose(f);
end
