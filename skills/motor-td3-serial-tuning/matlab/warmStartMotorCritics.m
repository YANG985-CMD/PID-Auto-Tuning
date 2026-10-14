function [networks,report]=warmStartMotorCritics(agent,replay,steps,seed)
% Fit TRAIN recorded finite returns. No validation gradients or plant model.
arguments
    agent
    replay (1,1) struct
    steps (1,1) double {mustBeInteger,mustBeNonnegative}
    seed (1,1) double
end
assert(steps<=2000 && all(cellfun(@(r)isfield(r,'logged_bounded_return'),replay.train)));
x=single(cell2mat(cellfun(@(r)r.observation(:),replay.train,UniformOutput=false)'));
a=single(cell2mat(cellfun(@(r)r.action_normalized(:),replay.train,UniformOutput=false)'));
y=single(cellfun(@(r)r.logged_bounded_return,replay.train)');
critics=getCritic(agent);networks=cell(1,2);records=cell(1,2);
for k=1:2
    rng(seed+5000+k,'twister');net=getModel(critics(k));
    average=[];squareAverage=[];
    for iteration=1:steps
        indices=randi(size(x,2),1,32);
        [loss,gradients]=dlfeval(@criticLoss,net,dlarray(x(:,indices),'CB'), ...
            dlarray(a(:,indices),'CB'),dlarray(y(:,indices),'CB'));
        assert(isfinite(double(extractdata(loss))));
        [net,average,squareAverage]=adamupdate(net,gradients,average,squareAverage,iteration,.001);
    end
    networks{k}=net;
    trainPrediction=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))));
    xv=single(cell2mat(cellfun(@(r)r.observation(:),replay.validation,UniformOutput=false)'));
    av=single(cell2mat(cellfun(@(r)r.action_normalized(:),replay.validation,UniformOutput=false)'));
    yv=cellfun(@(r)r.logged_bounded_return,replay.validation)';
    pred=double(extractdata(predict(net,dlarray(xv,'CB'),dlarray(av,'CB'))));
    records{k}=struct(train_rmse=sqrt(mean((trainPrediction-double(y)).^2)), ...
        validation_rmse=sqrt(mean((pred-yv).^2)), ...
        validation_constant_training_mean_rmse=sqrt(mean((mean(double(y))-yv).^2)));
end
report=struct(passed=true,steps_per_critic=steps,critics=[records{:}], ...
    warm_start_targets="Audited actual finite returns under recorded behavior", ...
    fit_split="Training boots only",hardware_accessed=false, ...
    not_new_policy_performance=true,deployment_allowed=false);
end

function [loss,gradients]=criticLoss(net,observation,action,target)
q=forward(net,observation,action);
loss=mean((q-target).^2,'all');
gradients=dlgradient(loss,net.Learnables);
end
