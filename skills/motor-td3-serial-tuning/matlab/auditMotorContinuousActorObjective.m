function report=auditMotorContinuousActorObjective(input,study,output)
% Frozen-gradient and bounded quadratic action audit. No optimizer or device I/O.
arguments
    input (1,1) string
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
assert(s.fullHallAudit.passed && motorFileSHA256(input)==string(summary.audited_input_sha256));
assert(string(summary.execution_mode)=="upper8-continuous-step-clamp");
train=s.fullHallTrain;valid=s.fullHallValidation;
x=matrix(train,'observation');a=matrix(train,'action_normalized');vx=matrix(valid,'observation');
levels=unique(a(1,:));groups=arrayfun(@(v)find(a(1,:)==v),levels,UniformOutput=false);
stream=RandStream('mt19937ar','Seed',63341);batches=zeros(12,32);
for k=1:12
    ids=randi(stream,numel(groups),1,32);
    for j=1:32,g=groups{ids(j)};batches(k,j)=g(randi(stream,numel(g)));end
end
results=struct([]);greedy=zeros(numel(summary.candidates),numel(valid));
for index=1:numel(summary.candidates)
    candidate=summary.candidates(index);path=fullfile(study,"candidate-complete-Hall-seed-"+candidate.seed+".mat");
    assert(motorFileSHA256(path)==string(candidate.checkpoint_sha256));p=load(path,'trainingState','contract');
    c=p.contract;t=p.trainingState;spec=motorStreamGainSpec(c.stream_gain_profile);
    rlWeight=summary.behavior_cloning_RL_weight;
    scale=single([2/(spec.action_upper_limit(1)-spec.action_lower_limit(1));1]);
    ratios=zeros(1,12);cosines=ratios;lambdas=ratios;norms=zeros(12,2);decompositionError=0;lossError=0;
    for k=1:12
        bx=dlarray(x(:,batches(k,:)),'CB');ba=dlarray(a(:,batches(k,:)),'CB');
        [rl,bc,lambda,totalLoss]=dlfeval(@parts,t.actor,t.critic1,bx,ba,scale,c,rlWeight);
        [actualLoss,total]=dlfeval(@motorTD3ActorLoss,t.actor,t.critic1,bx,ba,scale,c.q_value_shift, ...
            "unshifted-physical","upper8-continuous-step-clamp",c,rlWeight);
        u=vector(rl);v=vector(bc);w=vector(total);
        decompositionError=max(decompositionError,max(abs(w-u-v)));
        lossError=max(lossError,abs(double(extractdata(totalLoss-actualLoss))));
        norms(k,:)=[norm(u) norm(v)];ratios(k)=norm(u)/max(norm(v),realmin);
        cosines(k)=dot(u,v)/max(norm(u)*norm(v),realmin);lambdas(k)=lambda;
    end
    assert(decompositionError<1e-4 && lossError<1e-5);
    [beta1,parity1]=quadratic(t.critic1,vx,c);
    [beta2,parity2]=quadratic(t.critic2,vx,c);
    assert(max(parity1,parity2)<1e-7);
    actual=.003389*(double(vx(8,:))*c.state_scale(8)+c.state_center(8));
    encoded=(actual-c.encoded_baseline_gains(1))/c.gain_step_scale(1);
    step=.00013556/c.gain_step_scale(1);
    lower=max(spec.action_lower_limit(1),encoded-step);upper=min(spec.action_upper_limit(1),encoded+step);
    base=max(lower,min(upper,0));choice=zeros(size(base));benefit=choice;greedy1=choice;greedy2=choice;
    denseError=0;
    for j=1:numel(base)
        b1=beta1(:,j);b2=beta2(:,j);
        possible=[base(j) lower(j) upper(j) vertices(b1) vertices(b2) crossings(b1-b2)];
        possible=possible(isfinite(possible) & possible>=lower(j) & possible<=upper(j));
        q=min(polyval(b1,possible),polyval(b2,possible));[best,which]=max(q);choice(j)=possible(which);
        benefit(j)=best-min(polyval(b1,base(j)),polyval(b2,base(j)));
        dense=linspace(lower(j),upper(j),129);
        denseError=max(denseError,max(min(polyval(b1,dense),polyval(b2,dense)))-best);
        u=[base(j) lower(j) upper(j) vertices(b1)];u=u(isfinite(u)&u>=lower(j)&u<=upper(j));
        [~,w]=max(polyval(b1,u));greedy1(j)=u(w);
        u=[base(j) lower(j) upper(j) vertices(b2)];u=u(isfinite(u)&u>=lower(j)&u<=upper(j));
        [~,w]=max(polyval(b2,u));greedy2(j)=u(w);
    end
    assert(denseError<1e-10);
    greedy(index,:)=choice;
    policy=double(extractdata(motorTD3ExecutedAction(predict(t.actor,dlarray(vx,'CB')),dlarray(vx,'CB'),c)));
    policyQ=min(sum(beta1.*[policy(1,:).^2;policy(1,:);ones(1,size(vx,2))],1), ...
        sum(beta2.*[policy(1,:).^2;policy(1,:);ones(1,size(vx,2))],1));
    baseQ=min(sum(beta1.*[base.^2;base;ones(size(base))],1),sum(beta2.*[base.^2;base;ones(size(base))],1));
    row=struct(seed=candidate.seed,checkpoint_sha256=string(candidate.checkpoint_sha256), ...
        actor_RL_weight=rlWeight,balanced_actual_action_levels=levels, ...
        median_RL_to_BC_gradient_norm_ratio=median(ratios),RL_to_BC_gradient_norm_ratios=ratios, ...
        median_gradient_direction_cosine=median(cosines),gradient_norms=norms, ...
        median_lambda=median(lambdas),gradient_decomposition_max_error=decompositionError,loss_decomposition_error=lossError, ...
        quadratic_network_parity_max_error=max(parity1,parity2),analytic_optimum_vs_dense_grid_deficit=denseError, ...
        mean_continuous_greedy_Q_advantage=mean(benefit), ...
        mean_Actor_Q_advantage=mean(policyQ-baseQ), ...
        fraction_greedy_equals_reachable_baseline_move=mean(abs(choice-base)<1e-7), ...
        greedy_Kp_percent_range=100*c.gain_step_scale(1)*[min(choice) max(choice)]/c.encoded_baseline_gains(1), ...
        mean_Actor_gap_to_greedy_Q=mean(benefit-(policyQ-baseQ)), ...
        twin_greedy_action_agreement_fraction=mean(abs(greedy1-greedy2)<1e-3), ...
        training_performed=false,weights_changed=false,candidate_admission=false,deployment_allowed=false);
    if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
end
spread=max(greedy,[],1)-min(greedy,[],1);
report=struct(passed=true,results=results,unique_train_windows=numel(train),unique_validation_windows=numel(valid), ...
    gradient_batches_from_training_only=true,frozen_random_batches_shared_between_seeds=true, ...
    cross_seed_greedy_action_agreement_fraction=mean(spread<1e-3), ...
    mean_cross_seed_greedy_normalized_action_spread=mean(spread), ...
    analytic_search_respects_current_actual_gain_and_host_step=true, ...
    greedy_action_is_diagnostic_only_not_Actor=true,Q_values_are_not_measured_motor_performance=true, ...
    validation_not_used_for_updates=true,training_performed=false,weights_changed=false, ...
    hardware_accessed=false,actor_applied=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
function [rl,bc,lambda,total]=parts(actor,critic,x,recorded,scale,c,rlWeight)
action=motorTD3ExecutedAction(forward(actor,x),x,c,true);
q=predict(critic,x,action)-single(c.q_value_shift);
lambda=rlWeight/max(double(extractdata(mean(abs(q),'all'))),1e-6);
rlLoss=-lambda*mean(q,'all');bcLoss=mean((scale.*(action-recorded)).^2,'all');total=rlLoss+bcLoss;
rl=dlgradient(rlLoss,actor.Learnables,RetainData=true);bc=dlgradient(bcLoss,actor.Learnables);
end
function [b,parity]=quadratic(net,x,c)
w=double(extractdata(net.Learnables.Value{net.Learnables.Parameter=="Weights"}));
bias=double(extractdata(net.Learnables.Value{net.Learnables.Parameter=="Bias"}));
v=w(:)./double(single(c.critic_feature_scale));
constant=bias-sum(v.*double(single(c.critic_feature_center)));
state=double(x).*c.critic_input_mask(:);
b=[v(22)+v(33:42)'*state;v(21)+v(23:32)'*state;constant+v(1:10)'*state+v(11:20)'*state.^2];
u=linspace(0,.5,size(x,2));a=single([u;zeros(size(u))]);
q=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
parity=max(abs(q-sum(b.*[double(a(1,:)).^2;double(a(1,:));ones(size(u))],1)));
end
function u=vertices(b)
if abs(b(1))<1e-15,u=[];else,u=-b(2)/(2*b(1));end
end
function u=crossings(b)
if abs(b(1))<1e-15
    if abs(b(2))<1e-15,u=[];else,u=-b(3)/b(2);end
else
    u=roots(b);u=u(abs(imag(u))<1e-10);u=real(u(:))';
end
end
function v=vector(g)
parts=cellfun(@(x)double(extractdata(x(:))),g.Value,UniformOutput=false);v=cat(1,parts{:});
end
function x=matrix(rows,name)
v=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=single(cat(2,v{:}));
end
