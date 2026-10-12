function tests=testSpeedLoopResponseReplay
tests=functiontests(localfunctions);
end

function setupOnce(testCase)
root=string(getenv('MOTOR_TD3_RESPONSE_TEST_DATA'));
assert(startsWith(root,"E:\simulink\_codex_tmp\") && isfolder(root));
testCase.TestData.root=root;
end

function testStrictGateDoesNotCreateAgent(testCase)
root=testCase.TestData.root;
report=trainSpeedLoopResponseTD3(fullfile(root,'strict'),fullfile(root,'tests','blocked'),7);
verifyFalse(testCase,report.td3_training_performed);
verifyEqual(testCase,report.training_experiences,106);
verifyEqual(testCase,report.remaining_training_windows,22);
verifyEmpty(testCase,report.seed_reports);
verifyEmpty(testCase,dir(fullfile(root,'tests','blocked','*.mat')));
end

function testExploratoryReplayRemainsSeparate(testCase)
r=validateSpeedLoopResponseReplay(fullfile(testCase.TestData.root,'exploratory'));
verifyTrue(testCase,r.training_ready);
verifyTrue(testCase,r.summary.exploratory_only);
verifyEqual(testCase,numel(r.train),146);
verifyEqual(testCase,numel(r.validation),47);
verifyFalse(testCase,r.deployment_allowed);
end

function testActualKiNotRelabeled(testCase)
verifyError(testCase,@()validateSpeedLoopResponseReplay( ...
    fullfile(testCase.TestData.root,'exploratory'),[1;0]),'MotorTD3:MaskConflict');
end

function testHashTamperingRejected(testCase)
folder=copyDataset(testCase,'hash-tamper');
fid=fopen(fullfile(folder,'response-windows.jsonl'),'ab');
fwrite(fid,uint8(32));fclose(fid);
verifyError(testCase,@()validateSpeedLoopResponseReplay(folder),'MotorTD3:Hash');
end

function testDuplicateResponsesRejected(testCase)
folder=copyDataset(testCase,'duplicate');
file=fullfile(folder,'response-windows.jsonl');
text=fileread(file); items=splitlines(strtrim(text));
extra=unicode2native(char(string(items(1))+newline),'UTF-8');
fid=fopen(file,'ab');closer=onCleanup(@()fclose(fid));
fwrite(fid,extra);clear closer;
s=jsondecode(fileread(fullfile(folder,'window-summary.json')));
s.response_windows=s.response_windows+1;s.dataset_sha256=motorFileSHA256(file);
writeSummary(folder,s);
verifyError(testCase,@()validateSpeedLoopResponseReplay(folder),'MATLAB:assertion:failed');
end

function testDiscountMatchesNativeAgent(testCase)
agent=createMotorTD3(7);
verifyEqual(testCase,agent.AgentOptions.DiscountFactor,.99);
r=validateSpeedLoopResponseReplay(fullfile(testCase.TestData.root,'exploratory'));
verifyTrue(testCase,all(cellfun(@(x)x.discount_factor==.99,r.rows)));
end

function folder=copyDataset(testCase,name)
folder=fullfile(testCase.TestData.root,'tests',name);
if ~isfolder(folder),mkdir(folder);end
copyfile(fullfile(testCase.TestData.root,'exploratory','response-windows.jsonl'),folder);
copyfile(fullfile(testCase.TestData.root,'exploratory','window-summary.json'),folder);
end

function writeSummary(folder,s)
fid=fopen(fullfile(folder,'window-summary.json'),'wb');
fwrite(fid,unicode2native(jsonencode(s),'UTF-8'));fclose(fid);
end
