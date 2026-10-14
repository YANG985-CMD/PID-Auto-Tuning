function report=testMotorFeasibleFraction(input,output)
s=load(input);c=s.fullHallContract;c.execution_mode="bidirectional-feasible-fraction";
c.actor_raw_coordinates="feasible-fraction[-1,1]";c.critic_action_coordinates="absolute-target-v7";
rows=[s.fullHallTrain;s.fullHallValidation];n=numel(rows);
p=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,p{:}));
p=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);a=single(cat(2,p{:}));
raw=motorFeasibleFractionInverse(a,x,c);[mapped,m]=motorFeasibleFractionAction(raw,x,c);
actionError=max(abs(double(mapped(:)-a(:))));assert(actionError<1e-6);
physical=reshape(cellfun(@(r)r.actual_target_kp,rows),1,[]);gainError=max(abs(m.executed_float32_kp-physical));
assert(gainError<=double(eps(single(max(physical)))));
inputRaw=dlarray(single([linspace(-.9,.9,n);zeros(1,n)]),'CB');
g=dlfeval(@slope,inputRaw,x,c);d=double(extractdata(g(1,:)));
assert(all(d>0) && max(abs(d-m.half_feasible_span))<1e-7);
extreme=single([repmat([-1 1],1,n);zeros(1,2*n)]);[~,m2]=motorFeasibleFractionAction(extreme,repelem(x,1,2),c);
assert(all(abs(m2.executed_float32_kp-m2.actual_kp)<=.00013556+1e-9));
rejected=0;
for kind=1:4
    q=raw(:,1);c2=c;
    if kind==1,q(1)=NaN;elseif kind==2,q(2)=.1;elseif kind==3,q(1)=1.1;else,c2.critic_action_coordinates="unknown";end
    try,motorFeasibleFractionAction(q,x(:,1),c2);catch,rejected=rejected+1;end
end
assert(rejected==4);report=struct(passed=true,actual_rows=n,maximum_action_roundtrip_error=actionError, ...
    maximum_float32_gain_error=gainError,all_interior_output_slopes_strictly_positive=true, ...
    derivative_range=[min(d) max(d)],old_zero_gradient_removed_without_STE=true,invalid_cases_rejected=4, ...
    actual_replay_actions_and_rewards_unchanged=true,optimizer_updated=false,hardware_accessed=false, ...
    actor_applied=false,deployment_allowed=false,performance_claim_allowed=false);
assert(~isfile(output));f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function g=slope(a,x,c)
b=motorTD3ExecutedAction(a,x,c,true);g=dlgradient(sum(b(1,:)),a);
end
