function report=testMotorMeasuredSwitchGate(input,holdingInput,output)
% Reject holding-only or inconsistent transition labels before gradients.
arguments
    input (1,1) string
    holdingInput (1,1) string
    output (1,1) string
end
assert(~isfolder(output) && startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
mkdir(output);s=load(input);assert(s.fullHallAudit.passed);
assert(sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,s.fullHallTrain))==32);
assert(sum(cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,s.fullHallValidation))==32);
holding=s;
for group={'fullHallTrain','fullHallValidation'}
    for k=1:numel(holding.(group{1}))
        holding.(group{1}){k}.actual_source_kp=holding.(group{1}){k}.actual_target_kp;
    end
end
zeroFile=fullfile(output,'zero-switch-input.mat');save(zeroFile,'-struct','holding');
bad=s;bad.fullHallTrain{1}.actual_source_kp=bad.fullHallTrain{1}.actual_source_kp+.0001;
badFile=fullfile(output,'inconsistent-source-input.mat');save(badFile,'-struct','bad');
files=[holdingInput,string(zeroFile),string(badFile)];rejected=false(1,3);
for k=1:3
    target=fullfile(output,"rejected-training-"+k);
    try
        trainMotorFullHallTD3(files(k),"",target,2,Sampling='uniform', ...
            RewardModes='complete-Hall',Initialization='near-baseline',RequireMeasuredSwitches=true);
    catch err
        rejected(k)=strcmp(err.identifier,'MotorTD3:SwitchSupport');
    end
    assert(rejected(k) && isempty(dir(fullfile(target,'*.mat'))));
end
report=struct(passed=all(rejected),holding_only_input_rejected=rejected(1), ...
    zero_switch_input_rejected=rejected(2),inconsistent_switch_label_rejected=rejected(3), ...
    measured_train_switches=32,measured_validation_switches=32, ...
    gradient_updates=0,hardware_accessed=false,training_performed=false);
f=fopen(fullfile(output,'summary.json'),'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
