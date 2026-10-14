function report=diagnoseMotorQuadraticOptimizer(source,output)
% Freeze all TD3 labels. Select optimizer step only on training objectives.
arguments
    source (1,1) string
    output (1,1) string
end
assert(~isfolder(output) && startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
mkdir(output);rates=[.001 .0001 .00001];seeds=[7 17 27];steps=600;decay=.01;
contract=struct(learning_rates=rates,seeds=seeds,steps_per_fit=steps,ridge_weight=decay, ...
    targets_frozen=true,target_action_noise_applied=false,actor_updates=0, ...
    optimizer_selection_metric="mean training-only balanced ridge objective at steps 520/540/560/580/600", ...
    validation_not_used_for_selection=true,source_windows=782,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(output,'optimizer-contract.json'),contract);rows=struct([]);
for observation=["original","causal"]
    name="audited-input.mat";if observation=="causal",name="causal-input.mat";end
    input=fullfile(source,name);s=load(input);
    assert(s.fullHallAudit.passed);x=matrix(s.fullHallTrain,'observation');nx=matrix(s.fullHallTrain,'next_observation');
    a=matrix(s.fullHallTrain,'action_normalized');vx=matrix(s.fullHallValidation,'observation');
    vnx=matrix(s.fullHallValidation,'next_observation');va=matrix(s.fullHallValidation,'action_normalized');
    dt=cellfun(@(r)r.duration_us,s.fullHallTrain)';vdt=cellfun(@(r)r.duration_us,s.fullHallValidation)';
    raw=cellfun(@(r)r.reward,s.fullHallTrain)';vraw=cellfun(@(r)r.reward,s.fullHallValidation)';
    mask=s.fullHallContract.critic_input_mask(:);features=double(motorLocalQuadraticFeatures(x.*single(mask),a));
    center=mean(features,2);scale=max(std(features,0,2),1e-3);
    D=[((features-center)./scale)' ones(size(x,2),1)];
    VD=[((double(motorLocalQuadraticFeatures(vx.*single(mask),va))-center)./scale)' ones(size(vx,2),1)];
    levels=unique(a(1,:));groups=arrayfun(@(v)find(a(1,:)==v),levels,UniformOutput=false);
    weights=zeros(size(x,2),1);
    for group=groups,weights(group{1})=1/(numel(groups)*numel(group{1}));end
    assert(abs(sum(weights)-1)<1e-12);penalty=eye(43);penalty(43,43)=0;
    for seed=seeds
        checkpoint=fullfile(source,"train-"+observation+"-centered","candidate-complete-Hall-seed-"+seed+".mat");
        sourceSummary=jsondecode(fileread(fullfile(fileparts(checkpoint),'training-summary.json')));
        sourceCandidate=sourceSummary.candidates([sourceSummary.candidates.seed]==seed);
        assert(isscalar(sourceCandidate) && motorFileSHA256(checkpoint)==string(sourceCandidate.checkpoint_sha256));
        loaded=load(checkpoint,'trainingState','contract');t=loaded.trainingState;C=loaded.contract.q_value_shift;
        y=frozenTarget(t,nx,raw+C*(1-.99.^(dt/100000)),dt);
        vy=frozenTarget(t,vnx,vraw+C*(1-.99.^(vdt/100000)),vdt);
        exact=(D'*(weights.*D)+decay*penalty)\(D'*(weights.*double(y(:))));
        optimum=sum(weights.*(D*exact-double(y(:))).^2)+decay*sum(exact(1:42).^2);
        for rate=rates
            initial=createMotorTD3(seed,[1;0],0,CriticInitialValue=0,CriticInputMask=mask, ...
                CriticArchitecture="local-quadratic",CriticFeatureCenter=center,CriticFeatureScale=scale);
            critics=getCritic(initial);net=getModel(critics(1));avg=[];sq=[];rng(seed+200000,'twister');
            lossTrace=zeros(steps/20,3);trace=0;
            for k=1:steps
                groupIds=randi(numel(groups),1,32);ids=zeros(1,32);
                for sample=1:32,available=groups{groupIds(sample)};ids(sample)=available(randi(numel(available)));end
                [~,g]=dlfeval(@loss,net,dlarray(x(:,ids),'CB'),dlarray(a(:,ids),'CB'),dlarray(y(ids),'CB'),decay);
                [net,avg,sq]=adamupdate(net,g,avg,sq,k,rate);
                if mod(k,20)==0
                    prediction=predictQ(net,x,a);beta=coefficients(net);
                    objective=sum(weights.*(prediction(:)-double(y(:))).^2)+decay*sum(beta(1:42).^2);
                    trace=trace+1;lossTrace(trace,:)=[k objective max(0,objective-optimum)];
                end
            end
            p=predictQ(net,x,a);vp=predictQ(net,vx,va);beta=coefficients(net);
            tail=lossTrace(end-4:end,2);
            row=struct(observation=observation,seed=seed,learning_rate=rate,gradient_updates=steps, ...
                exact_training_ridge_objective=optimum,final_training_objective=lossTrace(end,2), ...
                tail_mean_training_objective=mean(tail),tail_max_training_objective=max(tail), ...
                final_objective_gap=lossTrace(end,3),train_rmse=sqrt(mean((p-double(y)).^2)), ...
                validation_rmse=sqrt(mean((vp-double(vy)).^2)), ...
                coefficient_distance_to_training_optimum=norm(beta-exact), ...
                checkpoint_source_sha256=motorFileSHA256(checkpoint),input_sha256=motorFileSHA256(input));
            assert(all(isfinite(lossTrace),'all') && all(isfinite(beta)));
            stem=observation+"-seed-"+seed+"-lr-"+string(rate);
            writematrix(lossTrace,fullfile(output,stem+"-loss.csv"));save(fullfile(output,stem+"-fit.mat"),'net','center','scale','exact','row');
            if isempty(rows),rows=row;else,rows(end+1)=row;end %#ok<AGROW>
            write(fullfile(output,'optimizer-progress.json'),struct(results=rows));
            disp(jsonencode(row));
        end
    end
end
objectives=arrayfun(@(r)mean([rows([rows.learning_rate]==r).tail_mean_training_objective]),rates);
[~,best]=min(objectives);
report=struct(passed=true,contract=contract,results=rows, ...
    learning_rates=rates,mean_training_tail_objectives=objectives,selected_learning_rate=rates(best), ...
    selected_from_training_only=true,total_gradient_updates=sum([rows.gradient_updates]), ...
    TD3_target_updates=0,actor_updates=0,new_physical_windows=0,hardware_accessed=false, ...
    optimizer_diagnostic_is_not_TD3_candidate_admission=true, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
write(fullfile(output,'optimizer-summary.json'),report);disp(jsonencode(rmfield(report,'results')));
end
function values=matrix(rows,name)
parts=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);values=single(cat(2,parts{:}));
end
function q=predictQ(net,x,a)
q=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
end
function y=frozenTarget(t,x,r,dt)
a=extractdata(predict(t.targetActor,dlarray(x,'CB')));a(2,:)=0;
y=motorElapsedTD3Target(single(r),single(predictQ(t.targetCritic1,x,a)), ...
    single(predictQ(t.targetCritic2,x,a)),dt,zeros(size(dt)));
end
function [value,g]=loss(net,x,a,y,decay)
value=mean((forward(net,x,a)-y).^2,'all');
for k=1:height(net.Learnables)
    if net.Learnables.Parameter(k)=="Weights",value=value+decay*sum(net.Learnables.Value{k}.^2,'all');end
end
g=dlgradient(value,net.Learnables);
end
function beta=coefficients(net)
beta=zeros(43,1);
for k=1:height(net.Learnables)
    if net.Learnables.Parameter(k)=="Weights",beta(1:42)=double(extractdata(net.Learnables.Value{k}));
    else,beta(43)=double(extractdata(net.Learnables.Value{k}));end
end
end
function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
