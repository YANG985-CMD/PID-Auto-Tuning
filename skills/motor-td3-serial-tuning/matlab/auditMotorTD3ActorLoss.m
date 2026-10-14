function report=auditMotorTD3ActorLoss(study,output)
% Read-only gradient diagnostic matching installed R2024b DPG+BC reduction.
arguments
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
records=summary.input_manifest(string({summary.input_manifest.split})=="train");
results=struct([]);
for candidate=summary.candidates(:)'
    file=fullfile(study,"candidate-"+string(candidate.reward_profile)+"-seed-"+candidate.seed+".mat");
    s=load(file,'experimentalAgent','contract');agent=s.experimentalAgent;
    observations=cell(numel(records),1);actions=observations;
    for index=1:numel(records)
        r=records(index);assert(motorFileSHA256(r.file)==string(r.sha256));
        [e,~]=motorLiveWindowExperience(jsondecode(fileread(r.file)),s.contract);
        observations{index}=e.Observation{1};actions{index}=e.Action{1};
    end
    x=single(cat(2,observations{:}));a=single(cat(2,actions{:}));
    actor=getModel(getActor(agent));critics=getCritic(agent);q={getModel(critics(1)),getModel(critics(2))};
    bounds=getActionInfo(agent);scale=single(2./(bounds.UpperLimit-bounds.LowerLimit));
    weight=agent.AgentOptions.BatchDataRegularizerOptions.BehaviorCloningRegularizerWeight;
    rng(551);ratios=zeros(12,1);norms=zeros(12,2);lambdas=zeros(12,1);cosines=zeros(12,1);
    for batch=1:12
        indices=randperm(size(x,2),32);
        [rl,bc,lambda]=dlfeval(@gradients,actor,q,dlarray(x(:,indices),'CB'), ...
            dlarray(a(:,indices),'CB'),dlarray(scale,'CB'),weight);
        u=[];v=[];
        for index=1:height(rl)
            u=[u;double(extractdata(rl.Value{index}(:)))]; %#ok<AGROW>
            v=[v;double(extractdata(bc.Value{index}(:)))]; %#ok<AGROW>
        end
        norms(batch,:)=[norm(u) norm(v)];ratios(batch)=norm(u)/max(norm(v),realmin);
        cosines(batch)=dot(u,v)/max(norm(u)*norm(v),realmin);lambdas(batch)=lambda;
    end
    row=struct(seed=candidate.seed,reward_profile=string(candidate.reward_profile), ...
        checkpoint_sha256=motorFileSHA256(file),training_batches=12,batch_size=32, ...
        regularizer_weight=weight,RL_to_BC_gradient_norm_ratios=ratios',gradient_norms=norms, ...
        median_RL_to_BC_gradient_ratio=median(ratios),median_RL_normalization=median(lambdas), ...
        gradient_direction_cosines=cosines',training_performed=false);
    if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
end
report=struct(source="read-only-actor-loss-gradient-audit",training_data_only=true, ...
    results=results,gradient_rule="Frozen lambda; min of two critics; action-range-scaled mean-square BC", ...
    installed_implementation="R2024b rl.grad.dpgNNBC", ...
    official_reference="https://www.mathworks.com/help/reinforcement-learning/ref/rl.option.rlbehaviorcloningregularizeroptions.html", ...
    weights_changed=false,hardware_accessed=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
for r=results,disp(jsonencode(struct(profile=r.reward_profile,seed=r.seed,median_RL_to_BC_gradient_ratio=r.median_RL_to_BC_gradient_ratio)));end
end

function [rl,bc,lambda]=gradients(actor,critics,x,actual,scale,weight)
action=forward(actor,x);q=min(predict(critics{1},x,action),predict(critics{2},x,action));
lambda=weight/double(extractdata(mean(abs(q),'all')));
rlLoss=-lambda*mean(q,'all');bcLoss=mean((scale.*(action-actual)).^2,'all');
rl=dlgradient(rlLoss,actor.Learnables,'RetainData',true);bc=dlgradient(bcLoss,actor.Learnables);
end
