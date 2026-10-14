function report = checkComparisonArtifacts(output)
% Structural and source audit. Does not access hardware or produce code.
root=fileparts(mfilename('fullpath'));if nargin==0,output=root;end
models={'MotorTunerComparison','MotorFOCShared'};counts=struct([]);references={};barWidths=[];
for n=1:2
    assert(strcmp(get_param(models{n},'BlockDiagramType'),'model'));
    set_param(models{n},'SimulationCommand','update');
    blocks=find_system(models{n},'LookUnderMasks','none','FollowLinks','off','Type','block');
    types=cellfun(@(b)get_param(b,'BlockType'),blocks,'UniformOutput',false);
    row=struct('model',models{n},'block_count',numel(blocks),'model_references',sum(strcmp(types,'ModelReference')), ...
        'MATLABFcn_count',sum(strcmp(types,'MATLABFcn')),'MATLABSystem_count',sum(strcmp(types,'MATLABSystem')));
    if isempty(counts),counts=row;else,counts(end+1)=row;end %#ok<AGROW>
    for k=1:numel(blocks)
        properties=get_param(blocks{k},'ObjectParameters');
        if isfield(properties,'ReferenceBlock')
            ref=get_param(blocks{k},'ReferenceBlock');
            if ~isempty(ref),references{end+1}=ref;end %#ok<AGROW>
        end
        if ismember(types{k},{'Mux','Demux','BusSelector'})
            p=get_param(blocks{k},'Position');barWidths(end+1)=p(3)-p(1); %#ok<AGROW>
        end
    end
end
assert(counts(1).model_references==1 && counts(1).MATLABFcn_count==0 && counts(1).MATLABSystem_count==0);
assert(all(barWidths<=8));
assert(all(cellfun(@(r)startsWith(r,{'simulink/','slpidlib/','mcbplantlib/','autolibpmsmexterior/'}),unique(references))));
dd=Simulink.data.dictionary.open(fullfile(root,'motor_comparison.sldd'));section=getSection(dd,'Design Data');
names={'Rs','L','flux','Pn','Udc','CurrKp','CurrKi','spd_kp','spd_ki'};parameters=struct;
for n=1:numel(names),value=getValue(getEntry(section,names{n}));parameters.(names{n})=double(value.Value);end
close(dd);
speedPID=Simulink.ID.getFullName('MotorFOCShared:1315');
assert(strcmp(get_param(speedPID,'UseKiTs'),'off'));
assert(strcmp(get_param(speedPID,'ControllerParametersSource'),'external'));
report=struct('compile_passed',true,'structural_counts',counts,'native_library_references',{unique(references)}, ...
    'custom_library_models_created',false,'opaque_custom_masks_created',false, ...
    'maximum_Mux_Demux_BusSelector_width_px',max(barWidths), ...
    'parameters_from_reference_dictionary',parameters,'mechanical_J_kgm2',75e-6, ...
    'mechanical_viscous_B_Nms',8e-5,'mechanical_parameters_hardware_identified',false, ...
    'speed_PI_integral_definition','UseKiTs off: Ki multiplied by the 0.001s internal integrator step', ...
    'speed_PI_source','Original FOC_Model.c integral update: 0.001F * speedloop_ELAPS_T * Integrator_PREV_U', ...
    'hardware_accessed',false,'deployment_allowed',false);
fid=fopen(fullfile(output,'model_artifact_check.json'),'w');fwrite(fid,jsonencode(report,PrettyPrint=true));fclose(fid);
disp(report);
end
