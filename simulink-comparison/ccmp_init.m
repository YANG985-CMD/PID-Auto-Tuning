function ccmp_init()
% Safe initialization: no hardware, ports or drivers are accessed.
root=fileparts(mfilename('fullpath')); addpath(root,'-end'); c=ccmp_config();
if ~isfolder(c.tmp), mkdir(c.tmp); end
Simulink.fileGenControl('set','CacheFolder',fullfile(c.tmp,'cache'), ...
    'CodeGenFolder',fullfile(c.tmp,'codegen'),'createDir',true);
[speed,loadProfile]=ccmp_scenario();
if ~evalin('base','exist(''ccmpSpeedRef'',''var'')'), assignin('base','ccmpSpeedRef',speed); end
if ~evalin('base','exist(''ccmpLoad'',''var'')'), assignin('base','ccmpLoad',loadProfile); end
if ~evalin('base','exist(''ccmpMethod'',''var'')'), assignin('base','ccmpMethod',5); end
nn=load(fullfile(root,'neural_pid_weights.mat')); td=jsondecode(fileread(fullfile(root,'td3_actor_source.json')));
for n=1:2
    assignin('base',sprintf('ccmpNN_W%d',n),nn.(sprintf('W%d',n)));
    assignin('base',sprintf('ccmpNN_b%d',n),nn.(sprintf('b%d',n)));
end
for n=1:3
    name=sprintf('fc%d',n); l=td.actor;
    w=find(strcmp({l.layer},name)&strcmp({l.parameter},'Weights'));
    b=find(strcmp({l.layer},name)&strcmp({l.parameter},'Bias'));
    assignin('base',sprintf('ccmpTD3_W%d',n),double(l(w).value));
    assignin('base',sprintf('ccmpTD3_b%d',n),double(l(b).value(:)));
end
contract=td.learning_contract;
assignin('base','ccmpTD3Center',contract.state_center(:));
assignin('base','ccmpTD3Scale',contract.state_scale(:));
assignin('base','ccmpTD3InputMask',contract.actor_input_mask(:));
assignin('base','ccmpTD3ActionScale',contract.actor_output_affine_scale(:));
assignin('base','ccmpTD3ActionBias',contract.actor_output_affine_bias(:));
assignin('base','ccmpTD3Baseline',contract.encoded_baseline_gains(:));
assignin('base','ccmpTD3KpLevels',double(single([.003121269 .00325344 .003389])));
[a,b]=ndgrid([-1 -.5 0 .5 1]); rules=ccmp_fuzzy_rules([a(:)';b(:)']);
assignin('base','ccmpFuzzyKp',reshape(rules(1,:),5,5));
assignin('base','ccmpFuzzyKi',reshape(rules(2,:),5,5));
if evalin('base','exist(''ccmpPlanOverride'',''var'')')
    plan=evalin('base','ccmpPlanOverride');
else
    plan=readmatrix(fullfile(root,'ai_approved_plan.csv'));
end
if size(plan,1)==1, plan=[plan;[max(6,plan(1,1)+1) plan(1,2:3)]]; end
assignin('base','ccmpPlanTime',plan(:,1)');
assignin('base','ccmpPlanKp',plan(:,2)');
assignin('base','ccmpPlanKi',plan(:,3)');
end
