function result=testMotorLiveWindowAudit(checkpoint,folder)
% Valid real historical windows and corrupt-frame rejection, no new motion.
s=load(checkpoint,'reportSeed');c=s.reportSeed.learning_contract;
files=dir(fullfile(folder,'window-*.json'));assert(~isempty(files));
for k=1:numel(files)
    r=jsondecode(fileread(fullfile(files(k).folder,files(k).name)));
    [e,key]=motorLiveWindowExperience(r,c);assert(isfinite(e.Reward) && strlength(key)>0);
end
r=jsondecode(fileread(fullfile(files(1).folder,files(1).name)));
bad=r;bad.state_history(1).seq=bad.state_history(1).seq-1;reject(bad,c);
bad=r;bad.response(1).applied_seq=999999;reject(bad,c);
bad=r;bad.response(1).ki=bad.response(1).ki*1.01;reject(bad,c);
bad=r;bad.response(1).fault=8;reject(bad,c);
bad=r;bad.source_stage_proof.run_seen=0;reject(bad,c);
bad=r;bad.reward=bad.reward+.01;reject(bad,c);
result=struct(passed=true,historical_windows=numel(files),negative_cases=6,hardware_accessed=false);
disp(jsonencode(result));
end

function reject(r,c)
caught=false;try,motorLiveWindowExperience(r,c);catch,caught=true;end
assert(caught,'Corrupt window was accepted');
end
