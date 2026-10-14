function report=testMotorActorValueCoordinates(output)
% A continuing value potential must not change detached TD3+BC weights.
agent=createMotorTD3(7,[1;0],0,CriticArchitecture="local-quadratic",CriticInitialValue=0);
actor=getModel(getActor(agent));critics=getCritic(agent);original=getModel(critics(1));
for k=1:height(original.Learnables)
    if original.Learnables.Parameter(k)=="Weights"
        w=zeros(1,42,'single');w(21)=.002;w(22)=-.001;
        original.Learnables.Value{k}=dlarray(w);
    else,original.Learnables.Value{k}=dlarray(single(-.125));end
end
shifted=original;C=.125;
for k=1:height(shifted.Learnables)
    if shifted.Learnables.Parameter(k)=="Bias",shifted.Learnables.Value{k}=shifted.Learnables.Value{k}+single(C);end
end
x=dlarray(single(reshape(1:80,10,8)/80),'CB');a=dlarray(single([linspace(-.2,.2,8);zeros(1,8)]),'CB');scale=single([4;1]);
[l0,g0,w0]=dlfeval(@motorTD3ActorLoss,actor,original,x,a,scale,0,"unshifted-physical");
[l1,g1,w1]=dlfeval(@motorTD3ActorLoss,actor,shifted,x,a,scale,C,"unshifted-physical");
[~,oldG,oldWeight]=dlfeval(@motorTD3ActorLoss,actor,shifted,x,a,scale,C,"native");
lossError=abs(double(extractdata(l0-l1)));gradientError=0;oldDifference=0;
for k=1:height(g0)
    gradientError=max(gradientError,max(abs(double(extractdata(g0.Value{k}-g1.Value{k}))),[],'all'));
    oldDifference=max(oldDifference,max(abs(double(extractdata(g0.Value{k}-oldG.Value{k}))),[],'all'));
end
assert(lossError<1e-4 && gradientError<1e-4 && abs(w0-w1)<1e-3);
assert(oldWeight>10*w0 && oldDifference>1);
report=struct(passed=true,loss_translation_error=lossError,gradient_translation_error=gradientError, ...
    unshifted_lambda=w0,translated_unshifted_lambda=w1,historical_native_lambda=oldWeight, ...
    historical_gradient_difference=oldDifference,historical_coordinate_bug_reproduced=true, ...
    fixed_Ki=true,hardware_accessed=false,actor_applied=false,candidate_admission=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
