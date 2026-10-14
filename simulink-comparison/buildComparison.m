function report = buildComparison(output)
% Rebuild from the read-only reference with MathWorks model_edit operations.
% Supplied .slx files run directly; this rebuild uses the installed toolkit.
source=fileparts(mfilename('fullpath')); c=ccmp_config();
if nargin==0,output='E:/dianji/motor-td3-simulink-comparison';end
assert(~isempty(which('model_edit')),'Comparison:BuildTool','The MathWorks Simulink agentic toolkit model_edit function is required to rebuild');
stage=fullfile(c.tmp,'rebuild');if ~isfolder(stage),mkdir(stage);end
for model={'MotorTunerComparison','MotorFOCShared'}
    if bdIsLoaded(model{1}),close_system(model{1},0);end
end
files=dir(source);
for n=1:numel(files)
    [~,~,ext]=fileparts(files(n).name);
    if ~strcmpi(strrep(source,'\','/'),strrep(stage,'\','/')) && ~files(n).isdir && ismember(ext,{'.m','.json','.csv','.mat'})
        copyfile(fullfile(source,files(n).name),fullfile(stage,files(n).name));
    end
end
copyfile(fullfile(c.reference,'speedloop.slx'),fullfile(stage,'MotorFOCShared.slx'));
copyfile(fullfile(c.reference,'speedloop.sldd'),fullfile(stage,'motor_comparison.sldd'));
addpath(stage,'-begin');cd(stage);ccmp_init();
open_system(fullfile(stage,'MotorFOCShared.slx'));
new_system('MotorTunerComparison');open_system('MotorTunerComparison');
manifest=jsondecode(fileread(fullfile(stage,'build_manifest.json')));
for n=1:numel(manifest.steps)
    item=manifest.steps(n);
    result=model_edit(item.model,item.scope,item.operations_json,item.layout);
    if ~contains(result,'status: ok')
        disp(model_read(item.model,item.scope,'0'));
        disp(model_check(item.model,item.scope,'["all"]'));
        error('Comparison:Build','Model edit %d was incomplete: %s',n,result);
    end
end
save_system('MotorFOCShared',fullfile(stage,'MotorFOCShared.slx'));
save_system('MotorTunerComparison',fullfile(stage,'MotorTunerComparison.slx'));
set_param('MotorFOCShared','SimulationCommand','update');
set_param('MotorTunerComparison','SimulationCommand','update');
if ~isfolder(output),mkdir(output);end
report=ccmp_layout(output);
save_system('MotorFOCShared');save_system('MotorTunerComparison');
copyfile(fullfile(stage,'MotorFOCShared.slx'),fullfile(output,'MotorFOCShared.slx'));
copyfile(fullfile(stage,'MotorTunerComparison.slx'),fullfile(output,'MotorTunerComparison.slx'));
copyfile(fullfile(stage,'motor_comparison.sldd'),fullfile(output,'motor_comparison.sldd'));
for n=1:numel(files)
    [~,~,ext]=fileparts(files(n).name);
    if ~strcmpi(strrep(source,'\','/'),strrep(char(output),'\','/')) && ~files(n).isdir && ismember(ext,{'.m','.json','.csv','.mat','.md'})
        copyfile(fullfile(source,files(n).name),fullfile(output,files(n).name));
    end
end
report.rebuilt_from_reference=true;report.compile_passed=true;
fid=fopen(fullfile(output,'build_check.json'),'w');fwrite(fid,jsonencode(report,PrettyPrint=true));fclose(fid);
end
