function report=testMotorActorRewardWeight(output)
% Check BC-only limit, explicit default parity and value-coordinate invariance.
agent=createMotorTD3(7,[1;0],0,CriticArchitecture="local-quadratic",CriticInitialValue=0);
actor=getModel(getActor(agent));critics=getCritic(agent);critic=getModel(critics(1));
for k=1:height(critic.Learnables)
    if critic.Learnables.Parameter(k)=="Weights"
        w=zeros(1,42,'single');w(21)=.002;w(22)=-.001;critic.Learnables.Value{k}=dlarray(w);
    else,critic.Learnables.Value{k}=dlarray(single(-.125));end
end
x=dlarray(single(reshape(1:80,10,8)/80),'CB');a=dlarray(single([linspace(-.2,.2,8);zeros(1,8)]),'CB');scale=single([4;1]);
[defaultLoss,defaultG,defaultLambda]=dlfeval(@motorTD3ActorLoss,actor,critic,x,a,scale,0);
[explicitLoss,explicitG,explicitLambda]=dlfeval(@motorTD3ActorLoss,actor,critic,x,a,scale,0, ...
    "unshifted-physical","continuous-experimental",struct,25);
assert(isequal(extractdata(defaultLoss),extractdata(explicitLoss)) && defaultLambda==explicitLambda);
assert(error(defaultG,explicitG)==0);
[bcLoss,bcG,lambda0]=dlfeval(@motorTD3ActorLoss,actor,critic,x,a,scale,0, ...
    "unshifted-physical","continuous-experimental",struct,0);
[expectedLoss,expectedG]=dlfeval(@pureBC,actor,x,a,scale);
assert(lambda0==0 && abs(double(extractdata(bcLoss-expectedLoss)))<1e-7 && error(bcG,expectedG)<1e-7);
[~,~,lambdaHigh]=dlfeval(@motorTD3ActorLoss,actor,critic,x,a,scale,0, ...
    "unshifted-physical","continuous-experimental",struct,2500);
assert(abs(lambdaHigh/defaultLambda-100)<1e-10);
shifted=critic;C=.125;
for k=1:height(shifted.Learnables)
    if shifted.Learnables.Parameter(k)=="Bias",shifted.Learnables.Value{k}=shifted.Learnables.Value{k}+single(C);end
end
[l1,g1]=dlfeval(@motorTD3ActorLoss,actor,shifted,x,a,scale,C, ...
    "unshifted-physical","continuous-experimental",struct,2500);
[l2,g2]=dlfeval(@motorTD3ActorLoss,actor,critic,x,a,scale,0, ...
    "unshifted-physical","continuous-experimental",struct,2500);
assert(abs(double(extractdata(l1-l2)))<.01 && error(g1,g2)<.01);
report=struct(passed=true,explicit_default_gradient_parity_error=error(defaultG,explicitG), ...
    zero_weight_matches_pure_behavior_cloning=true,weight_scale_100x_verified=true, ...
    value_coordinate_shift_invariance_verified=true,training_performed=false,hardware_accessed=false, ...
    actor_applied=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function [loss,g]=pureBC(net,x,a,scale)
p=forward(net,x);loss=mean((scale.*(p-a)).^2,'all');g=dlgradient(loss,net.Learnables);
end
function e=error(a,b)
e=0;for k=1:height(a),e=max(e,max(abs(double(extractdata(a.Value{k}-b.Value{k}))),[],'all'));end
end
