function report=exportMotorFeasibleDiagnosticJSON(checkpoint,output)
% Explicit custom checkpoint serialization, never a native agent or MCU export.
s=load(checkpoint);assert(s.contract.native_rl_agent_exported==false);
assert(s.contract.actor_raw_coordinates=="feasible-fraction[-1,1]" && s.contract.critic_action_coordinates=="absolute-target-v7");
assert(~s.candidateReport.deployment_allowed && ~s.candidateReport.performance_claim_allowed);
report=struct(source_checkpoint_sha256=motorFileSHA256(checkpoint),learning_contract=s.contract, ...
    candidate=s.candidateReport,actor=serialize(s.trainingState.actor),critic1=serialize(s.trainingState.critic1), ...
    critic2=serialize(s.trainingState.critic2),native_agent_exported=false,generated_mcu_code=false, ...
    raw_actor_coordinates="feasible-fraction[-1,1]",critic_action_coordinates="absolute-target-v7", ...
    deployment_allowed=false,performance_claim_allowed=false);
assert(~isfile(output));f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
r=jsondecode(fileread(output));check(s.trainingState.actor,r.actor);check(s.trainingState.critic1,r.critic1);check(s.trainingState.critic2,r.critic2);
end
function values=serialize(net)
v=cell(height(net.Learnables),1);
for k=1:numel(v),x=double(extractdata(net.Learnables.Value{k}));v{k}=struct(layer=net.Learnables.Layer(k),parameter=net.Learnables.Parameter(k),shape=size(x),value=x);end
values=[v{:}];
end
function check(net,values)
assert(height(net.Learnables)==numel(values));
for k=1:numel(values),assert(isequal(double(extractdata(net.Learnables.Value{k})),reshape(double(values(k).value),values(k).shape')));end
end
