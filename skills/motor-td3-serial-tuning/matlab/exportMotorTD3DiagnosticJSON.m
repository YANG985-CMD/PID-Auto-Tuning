function report=exportMotorTD3DiagnosticJSON(checkpoint,output)
% Serialize experimental Actor/dual-Critic weights for audit, never MCU C.
arguments
    checkpoint (1,1) string
    output (1,1) string
end
loaded=load(checkpoint,'agent','reportSeed');
actor=getModel(getActor(loaded.agent)); critics=getCritic(loaded.agent);
report=struct(schema_version=1,source_checkpoint_sha256=motorFileSHA256(checkpoint), ...
    source="experimental-real-data-offline-training",deployment_allowed=false, ...
    performance_claim_allowed=false,generated_mcu_code=false, ...
    action_mask=[1,double(~loaded.reportSeed.ki_masked)], ...
    input_type="Already normalized observation; clip each component to [-5,5]", ...
    state_scale=[1000,1000,1000,1000,3,2,24,.003389,.00144,3000], ...
    actor_architecture="10 -> 16 ReLU -> 16 ReLU -> 2 tanh", ...
    critic_architecture="concat(state10,action2) -> 32 ReLU -> 32 ReLU -> Q1", ...
    actor=serialize(actor),critic1=serialize(getModel(critics(1))), ...
    critic2=serialize(getModel(critics(2))));
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
