function critic=createMotorLocalQuadraticCritic(obs,act,initialValue,inputMask,center,scale)
% Forty-two features plus bias, with two separately initialized TD3 critics.
arguments
    obs
    act
    initialValue (1,1) double
    inputMask (10,1) double
    center (42,1) double
    scale (42,1) double
end
assert(all(isfinite([center;scale])) && all(scale>0));
mask=single(inputMask);offset=single(center);gain=single(scale);
net=dlnetwork;
net=addLayers(net,featureInputLayer(10,Normalization='none',Name='state'));
net=addLayers(net,featureInputLayer(2,Normalization='none',Name='action'));
net=addLayers(net,functionLayer(@(x,a)(motorLocalQuadraticFeatures(x.*mask,a)-offset)./gain, ...
    NumInputs=2,Formattable=true,Name='local_quadratic_features'));
net=addLayers(net,fullyConnectedLayer(1,Name='q'));
net=connectLayers(net,'state','local_quadratic_features/in1');
net=connectLayers(net,'action','local_quadratic_features/in2');
net=connectLayers(net,'local_quadratic_features','q');net=initialize(net);
if isfinite(initialValue)
    for k=1:height(net.Learnables)
        if net.Learnables.Parameter(k)=="Bias"
            net.Learnables.Value{k}=net.Learnables.Value{k}*single(0)+single(initialValue);
        else
            net.Learnables.Value{k}=net.Learnables.Value{k}*single(.001);
        end
    end
end
critic=rlQValueFunction(net,obs,act,ObservationInputNames='state',ActionInputNames='action');
end
