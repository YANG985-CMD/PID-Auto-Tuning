function report=exportMotorTD3DiagnosticJSON(checkpoint,output)
% Serialize experimental Actor/dual-Critic weights for audit, never MCU C.
arguments
    checkpoint (1,1) string
    output (1,1) string
end
loaded=load(checkpoint);
metadata=struct;contract=struct;
if isfield(loaded,'experimentalAgent')
    agent=loaded.experimentalAgent;
    if isfield(loaded,'reportSeed')
        metadata=loaded.reportSeed;contract=metadata.learning_contract;
        assert(~metadata.runtime_compatible);
    elseif isfield(loaded,'candidateReport') && isfield(loaded,'contract')
        metadata=loaded.candidateReport;contract=loaded.contract;
        assert(~metadata.deployment_allowed && ~metadata.performance_claim_allowed);
    else
        error('MotorTD3:Metadata','Experimental checkpoint has no explicit contract');
    end
else
    agent=loaded.agent;
    if isfield(loaded,'reportSeed'),metadata=loaded.reportSeed;end
end
if isfield(contract,'action_mask'),actionMask=contract.action_mask;
elseif isfield(metadata,'ki_masked'),actionMask=[1,double(~metadata.ki_masked)];
else,error('MotorTD3:Mask','Missing explicit action mask');end
actor=getModel(getActor(agent)); critics=getCritic(agent);
report=struct(schema_version=1,source_checkpoint_sha256=motorFileSHA256(checkpoint), ...
    source="experimental-real-data-offline-training",deployment_allowed=false, ...
    performance_claim_allowed=false,generated_mcu_code=false, ...
    action_mask=actionMask, ...
    input_type="Already normalized observation; clip each component to [-5,5]", ...
    state_scale=[1000,1000,1000,1000,3,2,24,.003389,.00144,3000], ...
    actor_architecture="10 -> 16 ReLU -> 16 ReLU -> 2 tanh", ...
    critic_architecture="concat(state10,action2) -> 32 ReLU -> 32 ReLU -> Q1", ...
    actor=serialize(actor),critic1=serialize(getModel(critics(1))), ...
    critic2=serialize(getModel(critics(2))));
if ~isempty(fieldnames(contract))
    report.learning_contract=contract;
    if isfield(report.learning_contract,'actor_output_affine_scale')
        report.actor_architecture="10 -> 16 ReLU -> 16 ReLU -> 2 tanh -> explicit affine range -> action mask";
    end
    if isfield(report.learning_contract,'critic_input_mask') && any(report.learning_contract.critic_input_mask==0)
        report.critic_architecture="explicit state mask -> concat(state10,action2) -> 32 ReLU -> 32 ReLU -> Q1";
    end
    if isfield(contract,'critic_architecture') && string(contract.critic_architecture)=="local-quadratic"
        report.critic_architecture="explicit state mask -> training-normalized local quadratic features -> linear Q (43 coefficients)";
    end
    report.runtime_compatible=false;
    report.input_type="Apply the explicit learning contract before inference; incompatible with current live loader";
end
fid=fopen(output,'wb'); assert(fid>=0);
closer=onCleanup(@()fclose(fid)); %#ok<NASGU>
fwrite(fid,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'),'uint8');
clear closer;
roundtrip=jsondecode(fileread(output));
assertWeightsEqual(actor,roundtrip.actor);
assertWeightsEqual(getModel(critics(1)),roundtrip.critic1);
assertWeightsEqual(getModel(critics(2)),roundtrip.critic2);
end

function result=serialize(network)
result=cell(height(network.Learnables),1);
for k=1:height(network.Learnables)
    value=double(extractdata(network.Learnables.Value{k}));
    result{k}=struct(layer=network.Learnables.Layer(k), ...
        parameter=network.Learnables.Parameter(k),shape=size(value),value=value);
end
result=[result{:}];
end

function assertWeightsEqual(network,values)
assert(height(network.Learnables)==numel(values));
for k=1:numel(values)
    expected=double(extractdata(network.Learnables.Value{k}));
    actual=reshape(double(values(k).value),values(k).shape');
    assert(isequal(expected,actual),'JSON weight roundtrip differs from MATLAB');
end
end
