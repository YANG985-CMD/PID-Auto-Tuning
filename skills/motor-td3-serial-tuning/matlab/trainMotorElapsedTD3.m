function report=trainMotorElapsedTD3(replay,normalizationCheckpoint,output,steps)
% MATLAB TD3 experiment with measured-duration discount and once-per-decision rewards.
% Custom updates; rlTD3Agent containers are for inference/replay audit only.
arguments
    replay (1,1) string
    normalizationCheckpoint (1,1) string
    output (1,1) string
    steps (1,1) double {mustBeInteger,mustBePositive}=600
end
assert(steps<=1200 && mod(steps,2)==0 && ~isfolder(output));mkdir(output);
tested=testMotorElapsedTD3(replay,normalizationCheckpoint);assert(tested.passed);
source=jsondecode(fileread(fullfile(replay,'summary.json')));s=load(normalizationCheckpoint,'contract');contract=s.contract;
contract.stream_gain_profile="lower8-sampling";spec=motorStreamGainSpec(contract.stream_gain_profile);
contract.action_lower_limit=spec.action_lower_limit;contract.action_upper_limit=spec.action_upper_limit;
contract.actor_output_affine_scale=spec.output_scale;contract.actor_output_affine_bias=spec.output_bias;
mask=[ones(9,1);0];contract.actor_input_mask=mask';contract.critic_input_mask=mask';
contract.action_mask=[1 0];contract.actor_actual_kp_input_masked=false;contract.actor_elapsed_time_masked=true;
contract.older_fixed_cadence_replay_excluded=true;contract.runtime_compatible=false;contract.online_learning=false;
contract.custom_elapsed_trainer=true;contract.native_trainFromData_resume_allowed=false;
train={};validation={};
for item=source.input_manifest(:)'
    assert(motorFileSHA256(item.file)==string(item.sha256));w=jsondecode(fileread(item.file));
    [e,key]=motorLiveWindowExperience(w,contract);
    row=struct(observation=double(e.Observation{1}),next_observation=double(e.NextObservation{1}), ...
        action_normalized=double(e.Action{1}),reward=w.time_scaled_reward,legacy_reward=e.Reward, ...
        duration_us=w.duration_us,measured_reward_span_us=w.measured_reward_span_us,discount=w.elapsed_discount, ...
        boot_id=string(w.boot_id),telemetry_seq_start=w.state.seq,learning_is_done=false,physical_key=key);
    if string(item.split)=="train",train{end+1,1}=row;else,validation{end+1,1}=row;end %#ok<AGROW>
end
assert(numel(train)==45 && numel(validation)==45 && numel(unique(cellfun(@(r)r.physical_key,train)))==45);
trainX=matrix(train,"observation");trainNext=matrix(train,"next_observation");trainA=matrix(train,"action_normalized");
reward=single(cellfun(@(r)r.reward,train)');duration=cellfun(@(r)r.duration_us,train)';
report=struct(source="MATLAB-custom-measured-time-TD3-experiment",training_backend="dlnetwork+dlgradient+adamupdate", ...
    native_trainFromData_called=false,reference_period_us=100000,reference_discount=.99, ...
    target_rule="reward+(1-done)*0.99^(elapsed_us/100000)*min(targetQ1,targetQ2)", ...
    actor_rule="Optimize first critic plus range-scaled behavior cloning; delayed every2 critic steps", ...
    target_noise_std=.05,target_noise_clip=.1,target_tau=.005,actor_learning_rate=1e-4,critic_learning_rate=.001, ...
    batch_size=32,seeds=[7 17 27],modes=["constant-step","measured-time"],steps_per_candidate=steps, ...
    behavior_cloning_RL_weight=25,unique_train_decisions=45,unique_validation_decisions=45, ...
    data_manifest=source.input_manifest,learning_contract=contract,old_short_windows_also_appended=false, ...
    unmeasured_latency_cost_estimated=false,actor_applied=false,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false,candidates=struct([]));
write(fullfile(output,'study-contract.json'),report);
for mode=report.modes
    effectiveDuration=duration;if mode=="constant-step",effectiveDuration(:)=100000;end
    initialQ=mean(double(reward))/(1-mean(.99.^(effectiveDuration/100000)));
    for seed=report.seeds
        initial=createMotorTD3(seed,[1;0],0,ActorInputMask=mask,CriticInputMask=mask, ...
            CriticInitialValue=initialQ,CriticL2RegularizationFactor=0, ...
            ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:));
        actor=getModel(getActor(initial));initialActor=actor;c=getCritic(initial);q1=getModel(c(1));q2=getModel(c(2));
        targetActor=actor;targetQ1=q1;targetQ2=q2;
        av=[];as=[];c1v=[];c1s=[];c2v=[];c2s=[];actorSteps=0;history=zeros(steps,4);
        for iteration=1:steps
            ids=randi(numel(train),1,32);x=dlarray(trainX(:,ids),'CB');nx=dlarray(trainNext(:,ids),'CB');a=dlarray(trainA(:,ids),'CB');
            nextA=single(extractdata(predict(targetActor,nx)));
            noise=max(-.1,min(.1,single(randn(1,32)*.05)));
            nextA(1,:)=max(-1,min(0,nextA(1,:)+noise));nextA(2,:)=0;
            nq1=single(extractdata(predict(targetQ1,nx,dlarray(nextA,'CB'))));
            nq2=single(extractdata(predict(targetQ2,nx,dlarray(nextA,'CB'))));
            y=motorElapsedTD3Target(reward(ids),nq1,nq2,effectiveDuration(ids),zeros(1,32));
            [l1,g1]=dlfeval(@criticLoss,q1,x,a,dlarray(y,'CB'));
            [l2,g2]=dlfeval(@criticLoss,q2,x,a,dlarray(y,'CB'));
            [q1,c1v,c1s]=adamupdate(q1,g1,c1v,c1s,iteration,.001);
            [q2,c2v,c2s]=adamupdate(q2,g2,c2v,c2s,iteration,.001);
            lossA=NaN;lambda=NaN;
            if mod(iteration,2)==0
                [la,ga,lambda]=dlfeval(@actorLoss,actor,q1,x,a);
                actorSteps=actorSteps+1;[actor,av,as]=adamupdate(actor,ga,av,as,actorSteps,1e-4);
                lossA=double(extractdata(la));
                targetActor=blend(targetActor,actor,.005);targetQ1=blend(targetQ1,q1,.005);targetQ2=blend(targetQ2,q2,.005);
            end
            history(iteration,:)=[double(extractdata(l1)),double(extractdata(l2)),lossA,lambda];
            assert(all(isfinite(history(iteration,1:2))));
        end
        observationInfo=getObservationInfo(initial);actionInfo=getActionInfo(initial);
        trainedActor=rlContinuousDeterministicActor(actor,observationInfo,actionInfo,'ObservationInputNames','state');
        critics=[rlQValueFunction(q1,observationInfo,actionInfo,'ObservationInputNames','state','ActionInputNames','action'), ...
            rlQValueFunction(q2,observationInfo,actionInfo,'ObservationInputNames','state','ActionInputNames','action')];
        options=initial.AgentOptions;options.InfoToSave=struct(ExperienceBuffer=true,Optimizer=false,PolicyState=true,Target=false);
        experimentalAgent=rlTD3Agent(trainedActor,critics,options);experimentalAgent.UseExplorationPolicy=false;
        for r=train'
            e=struct('Observation',{{single(r{1}.observation(:))}},'Action',{{single(r{1}.action_normalized(:))}}, ...
                'Reward',r{1}.reward,'NextObservation',{{single(r{1}.next_observation(:))}},'IsDone',0);
            validateExperience(experimentalAgent.ExperienceBuffer,e);append(experimentalAgent.ExperienceBuffer,e);
        end
        diagnosed=diagnoseMotorTD3Policy(experimentalAgent,validation,"continuing",[-.9875 0]);
        testX=matrix(validation,"observation");testNext=matrix(validation,"next_observation");testA=matrix(validation,"action_normalized");
        nextPolicy=single(extractdata(predict(targetActor,dlarray(testNext,'CB'))));
        testDuration=cellfun(@(r)r.duration_us,validation)';if mode=="constant-step",testDuration(:)=100000;end
        testY=motorElapsedTD3Target(cellfun(@(r)r.reward,validation)', ...
            extractdata(predict(targetQ1,dlarray(testNext,'CB'),dlarray(nextPolicy,'CB'))), ...
            extractdata(predict(targetQ2,dlarray(testNext,'CB'),dlarray(nextPolicy,'CB'))),testDuration,zeros(1,numel(validation)));
        logged1=single(extractdata(predict(q1,dlarray(testX,'CB'),dlarray(testA,'CB'))));
        logged2=single(extractdata(predict(q2,dlarray(testX,'CB'),dlarray(testA,'CB'))));
        candidateReport=struct(mode=mode,seed=seed,learning_contract=contract, ...
            custom_critic_update_iterations=steps,custom_actor_updates=actorSteps,native_gradient_steps=0, ...
            initial_critic_value=initialQ,validation=diagnosed.metrics, ...
            validation_native_diagnostic_uses_fixed_gamma=.99, ...
            duration_aware_target_residual_rmse=[sqrt(mean((logged1-testY).^2)),sqrt(mean((logged2-testY).^2))], ...
            residual_basis="Stored target networks, deterministic target Actor, declared elapsed mode; diagnostic only", ...
            actor_weight_change_l2=distance(initialActor,actor),inference_agent_only=true, ...
            target_optimizer_state_stored_separately=true,training_decisions=45,validation_decisions=45, ...
            deployment_allowed=false,performance_claim_allowed=false);
        trainingState=struct(actor=actor,critic1=q1,critic2=q2,targetActor=targetActor,targetCritic1=targetQ1,targetCritic2=targetQ2, ...
            actor_average=av,actor_square_average=as,critic1_average=c1v,critic1_square_average=c1s, ...
            critic2_average=c2v,critic2_square_average=c2s,critic_iterations=steps,actor_iterations=actorSteps,rng_state=rng);
        name="candidate-"+mode+"-seed-"+seed;
        save(fullfile(output,name+".mat"),'experimentalAgent','contract','candidateReport','trainingState');
        candidateReport.checkpoint_sha256=motorFileSHA256(fullfile(output,name+".mat"));
        if isempty(report.candidates),report.candidates=candidateReport;else,report.candidates(end+1)=candidateReport;end
        writetable(diagnosed.predictions,fullfile(output,name+"-holdout.csv"));
        writematrix(history,fullfile(output,name+"-loss.csv"));
        exportMotorTD3DiagnosticJSON(fullfile(output,name+".mat"),fullfile(output,name+"-networks.json"));
        fprintf('Completed custom TD3 %s seed%d, %d critic steps/%d actor updates\n',mode,seed,steps,actorSteps);
    end
end
report.custom_critic_update_iterations=sum([report.candidates.custom_critic_update_iterations]);
report.custom_actor_updates=sum([report.candidates.custom_actor_updates]);report.native_gradient_steps=0;
report.candidate_admission=false;report.reason="Limited real decision data and no independent frozen Actor physical response";
write(fullfile(output,'training-summary.json'),report);
end

function [loss,g]=criticLoss(net,x,a,y)
q=forward(net,x,a);loss=mean((q-y).^2,'all');g=dlgradient(loss,net.Learnables);
end
function [loss,g,lambda]=actorLoss(net,critic,x,actual)
action=forward(net,x);q=predict(critic,x,action);lambda=25/max(double(extractdata(mean(abs(q),'all'))),1e-6);
loss=-lambda*mean(q,'all')+mean((single([2;1]).*(action-actual)).^2,'all');g=dlgradient(loss,net.Learnables);
end
function target=blend(target,live,tau)
for index=1:height(target.Learnables),target.Learnables.Value{index}=(1-tau)*target.Learnables.Value{index}+tau*live.Learnables.Value{index};end
end
function d=distance(a,b)
d=0;for index=1:height(a.Learnables),d=d+sum(double(extractdata(a.Learnables.Value{index}-b.Learnables.Value{index})).^2,'all');end;d=sqrt(d);
end
function write(path,value)
f=fopen(path,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(value,PrettyPrint=true),'UTF-8'));fclose(f);
end
function x=matrix(rows,name)
vectors=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=single(cat(2,vectors{:}));
end
