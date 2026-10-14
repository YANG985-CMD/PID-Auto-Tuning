function report=auditMotorFeasibleGradients(input,study,output)
% Diagnose true clipping gradients, not policy performance or new evidence.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);c=s.fullHallContract;rows=[s.fullHallTrain;s.fullHallValidation];n=numel(rows);
assert(s.fullHallAudit.passed && c.execution_mode=="bidirectional-continuous-step-clamp");
parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
source=cellfun(@(r)r.actual_source_kp,rows);target=cellfun(@(r)r.actual_target_kp,rows);
boots=string(cellfun(@(r)r.boot_id,rows,UniformOutput=false));split=repmat("validation",n,1);split(1:numel(s.fullHallTrain))="train";
T=table(boots,split,source,target,source~=target,VariableNames=["Boot","Split","SourceKp","TargetKp","Switched"]);
parts=cellfun(@(r)r.action_normalized(:),s.fullHallTrain,UniformOutput=false);
sampler=prepareMotorBidirectionalSwitchSampler(single(cat(2,parts{:})),source(1:numel(s.fullHallTrain)),target(1:numel(s.fullHallTrain)),boots(1:numel(s.fullHallTrain)));
weights=zeros(n,1);
for k=1:numel(sampler.groups)
    group=sampler.groups{k};prob=[1-group.switch_probability group.switch_probability]/numel(sampler.groups);
    for status=1:2
        bucket=group.indices{status};
        for b=1:numel(bucket),ids=bucket{b};weights(ids)=prob(status)/numel(bucket)/numel(ids);end
    end
end
assert(abs(sum(weights)-1)<1e-12);
initial=zeros(2,n,'single');g=dlfeval(@slope,dlarray(initial,'CB'),x,c);initialSlope=double(extractdata(g(1,:)))';
referenceZeroSlope=initialSlope==0;
assert(all(ismember(initialSlope,[0 1])));
summ=jsondecode(fileread(fullfile(study,'training-summary.json')));results=struct([]);
for item=summ.candidates(:)'
    path=fullfile(study,"candidate-complete-Hall-seed-"+item.seed+".mat");assert(motorFileSHA256(path)==string(item.checkpoint_sha256));
    p=load(path,'trainingState','contract','candidateReport');assert(p.candidateReport.initial_zero_state_normalized_action(1)==0);
    assert(motorFileSHA256(which('createMotorTD3'))==string(summ.actor_constructor_source_sha256));
    spec=motorStreamGainSpec(c.stream_gain_profile);
    initialAgent=createMotorTD3(item.seed,[1;0],0,ActorInputMask=c.actor_input_mask(:),CriticInputMask=c.critic_input_mask(:), ...
        CriticInitialValue=p.contract.critic_initial_value,CriticArchitecture="local-quadratic", ...
        CriticFeatureCenter=p.contract.critic_feature_center,CriticFeatureScale=p.contract.critic_feature_scale, ...
        InitialNormalizedAction=[0;0],ActionLowerLimit=spec.action_lower_limit(:),ActionUpperLimit=spec.action_upper_limit(:));
    initialNet=getModel(getActor(initialAgent));initialRaw=predict(initialNet,dlarray(x,'CB'));
    g=dlfeval(@slope,initialRaw,x,p.contract);initialDerivative=double(extractdata(g(1,:)))';
    T.InitialZeroSlope=initialDerivative==0;
    a=predict(p.trainingState.actor,dlarray(x,'CB'));g=dlfeval(@slope,a,x,p.contract);derivative=double(extractdata(g(1,:)))';
    assert(all(ismember(derivative,[0 1])));T.FinalZeroSlope=derivative==0;
    grouped=groupsummary(T,["Split","SourceKp"],"mean",["InitialZeroSlope","FinalZeroSlope"]);
    value=struct(seed=item.seed,initial_all_rows_zero_gradient_fraction=mean(T.InitialZeroSlope), ...
        reconstructed_actual_initial_actor=true,initial_raw_action_range=[min(extractdata(initialRaw(1,:))) max(extractdata(initialRaw(1,:)))], ...
        initial_loss_sampling_zero_gradient_fraction=sum(weights.*T.InitialZeroSlope), ...
        final_all_rows_zero_gradient_fraction=mean(T.FinalZeroSlope), ...
        final_loss_sampling_zero_gradient_fraction=sum(weights.*T.FinalZeroSlope), ...
        final_validation_zero_gradient_fraction=mean(T.FinalZeroSlope(T.Split=="validation")), ...
        by_source_and_split=table2struct(grouped),network_weights_updated=false);
    if isempty(results),results=value;else,results(end+1)=value;end %#ok<AGROW>
end
report=struct(passed=true,results=results,actual_rows=n,actual_training_rows=numel(s.fullHallTrain), ...
    actual_validation_rows=numel(s.fullHallValidation),gradient_is_d_executed_absolute_action_d_raw_action=true, ...
    true_autodiff_clipping_gradient_used=true,sampling_weights_match_existing_sampler=true, ...
    raw_actions_are_absolute_target_coordinates=true,zero_target_reference_all_rows_zero_gradient_fraction=mean(referenceZeroSlope), ...
    zero_target_reference_loss_weighted_zero_gradient_fraction=sum(weights.*referenceZeroSlope), ...
    input_sha256=motorFileSHA256(input),training_summary_sha256=motorFileSHA256(fullfile(study,'training-summary.json')), ...
    new_physical_data=0,optimizer_updates=0,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(struct(passed=true,results=rmfield(results,'by_source_and_split'))));
end
function g=slope(a,x,c)
b=motorTD3ExecutedAction(a,x,c,true);g=dlgradient(sum(b(1,:)),a);
end
