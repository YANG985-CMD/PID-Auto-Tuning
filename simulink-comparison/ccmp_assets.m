function a = ccmp_assets()
% Read frozen assets once. runComparison clears this function between runs.
persistent saved
if isempty(saved)
    root = fileparts(mfilename('fullpath'));
    saved.nn = load(fullfile(root,'neural_pid_weights.mat'),'W1','b1','W2','b2','report');
    saved.td3 = jsondecode(fileread(fullfile(root,'td3_actor_source.json')));
    if evalin('base','exist(''ccmpPlanOverride'',''var'')')
        saved.plan=evalin('base','ccmpPlanOverride');
    else
        saved.plan = readmatrix(fullfile(root,'ai_approved_plan.csv'));
    end
end
a = saved;
end
