function report=testMotorLocalQuadraticCritic(output)
arguments
    output (1,1) string
end
assert(~isfile(output));mask=[ones(9,1);0];
agent=createMotorTD3(7,[1;0],0,CriticInitialValue=0,CriticInputMask=mask,CriticArchitecture="local-quadratic");
critics=getCritic(agent);net=getModel(critics(1));other=getModel(critics(2));
assert(any(extractdata(net.Learnables.Value{1})~=extractdata(other.Learnables.Value{1}),'all'));
w=single(1:42)/10000;bias=single(.01);
for k=1:height(net.Learnables)
    if net.Learnables.Parameter(k)=="Weights",net.Learnables.Value{k}=dlarray(w);
    else,net.Learnables.Value{k}=dlarray(bias);end
end
x=single(reshape(1:30,10,3)/30);a=single([-.25 0 .25;0 17 -20]);mx=x.*single(mask);
linear=w(21)+w(23:32)*mx;quadratic=w(22)+w(33:42)*mx;
expected=bias+w(1:10)*mx+w(11:20)*(mx.^2)+linear.*a(1,:)+quadratic.*a(1,:).^2;
actual=extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB')));
error=max(abs(double(actual-expected)));assert(error<1e-6);
[~,g]=dlfeval(@derivative,net,dlarray(x,'CB'),dlarray(a,'CB'));
expectedGradient=linear+2*quadratic.*a(1,:);
gradientError=max(abs(double(extractdata(g(1,:))-expectedGradient)));
assert(gradientError<1e-6 && all(extractdata(g(2,:))==0));
changed=x;changed(10,:)=1000;
assert(isequal(actual,extractdata(predict(net,dlarray(changed,'CB'),dlarray(a,'CB')))));
assert(all(quadratic>0),'Positive curvature must remain representable');
legacy=createMotorTD3Legacy(7,[1;0],0,CriticInitialValue=0,CriticInputMask=mask);
default=createMotorTD3(7,[1;0],0,CriticInitialValue=0,CriticInputMask=mask);
for type={'actor','critics'}
    if strcmp(type{1},'actor'),oldNets={getModel(getActor(legacy))};newNets={getModel(getActor(default))};
    else
        oldQ=getCritic(legacy);newQ=getCritic(default);
        oldNets={getModel(oldQ(1)),getModel(oldQ(2))};newNets={getModel(newQ(1)),getModel(newQ(2))};
    end
    for j=1:numel(oldNets)
        assert(isequal(oldNets{j}.Learnables.Layer,newNets{j}.Learnables.Layer));
        for k=1:height(oldNets{j}.Learnables)
            assert(isequal(extractdata(oldNets{j}.Learnables.Value{k}),extractdata(newNets{j}.Learnables.Value{k})));
        end
    end
end
rejected=false;
try,createMotorTD3(7,[1;1],0,CriticArchitecture="local-quadratic");
catch err,rejected=strcmp(err.identifier,'MotorTD3:QuadraticMask');end
assert(rejected);
report=struct(passed=true,polynomial_numeric_error=error,action_gradient_error=gradientError, ...
    fixed_Ki_ignored_by_critic=true,masked_state_independence=true,positive_curvature_supported=true, ...
    twin_initializations_distinct=true,legacy_default_learnables_identical=true,joint_Ki_mode_rejected=true, ...
    hardware_accessed=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function [q,g]=derivative(net,x,a)
q=sum(forward(net,x,a),'all');g=dlgradient(q,a);
end
