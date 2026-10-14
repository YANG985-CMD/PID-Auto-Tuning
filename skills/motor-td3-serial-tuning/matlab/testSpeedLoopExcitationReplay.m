function report=testSpeedLoopExcitationReplay(dataset,output)
% Reject corrupted hashes, duplicate commands, fixed-Ki and reference errors.
arguments
    dataset (1,1) string
    output (1,1) string
end
assert(startsWith(output,"E:/simulink/_codex_tmp/") || startsWith(output,"E:\simulink\_codex_tmp\"));
original=motorFileSHA256(fullfile(dataset,'response-windows.jsonl'));
summary=jsondecode(fileread(fullfile(dataset,'window-summary.json')));
text=splitlines(strtrim(fileread(fullfile(dataset,'response-windows.jsonl'))));
base=cellfun(@jsondecode,cellstr(text),UniformOutput=false);
names=["hash","duplicate-command","fixed-ki","reference"];
failures=cell(4,1);
for k=1:4
    rows=base;
    if k==1,rows{1}.reward=rows{1}.reward+.01;
    elseif k==2,rows{2}.source_command_seqs(1)=rows{1}.source_command_seqs(1);
    elseif k==3,rows{1}.action_applied(2)=.001476;
    else,rows{1}.reference_response_schedule(1).speed_ref=123;end
    d=fullfile(output,names(k));if ~isfolder(d),mkdir(d);end
    encoded=cellfun(@jsonencode,rows,UniformOutput=false);
    f=fopen(fullfile(d,'response-windows.jsonl'),'wb');assert(f>=0);
    fwrite(f,unicode2native(strjoin(string(encoded),newline)+newline,'UTF-8'));fclose(f);
    modified=summary;
    if k~=1,modified.dataset_sha256=motorFileSHA256(fullfile(d,'response-windows.jsonl'));end
    f=fopen(fullfile(d,'window-summary.json'),'wb');assert(f>=0);
    fwrite(f,unicode2native(jsonencode(modified),'UTF-8'));fclose(f);
    rejected=false;identifier="";
    try
        validateSpeedLoopResponseReplay(d,[1;0]);
    catch exception
        rejected=true;identifier=string(exception.identifier);
    end
    assert(rejected,"Corrupted replay unexpectedly admitted");
    failures{k}=struct(case_name=names(k),rejected=rejected,identifier=identifier);
end
assert(original==motorFileSHA256(fullfile(dataset,'response-windows.jsonl')));
report=struct(passed=true,tests=4,source_unchanged=true,checks=[failures{:}],hardware_accessed=false);
f=fopen(fullfile(output,'summary.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
end
