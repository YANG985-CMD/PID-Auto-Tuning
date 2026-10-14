function report = trainNeuralPID(output)
% Reproducible supervised demonstration. Labels are fuzzy rules, not hardware.
if nargin==0, output=fileparts(mfilename('fullpath')); end
rng(17,'twister'); [a,b]=ndgrid(linspace(-1,1,41)); X=[a(:)';b(:)'];
Y=ccmp_fuzzy_rules(X); W1=randn(12,2)*.3; b1=zeros(12,1);
W2=randn(2,12)*.1; b2=zeros(2,1); moments=cell(4,2); loss=zeros(2500,1);
for iteration=1:2500
    H=tanh(W1*X+b1); O=tanh(W2*H+b2); loss(iteration)=mean((O-Y).^2,'all');
    D=(O-Y).*(1-O.^2)/size(X,2); E=(W2'*D).*(1-H.^2);
    g={E*X',sum(E,2),D*H',sum(D,2)}; v={W1,b1,W2,b2};
    for k=1:4
        if isempty(moments{k,1}), moments{k,1}=zeros(size(v{k})); moments{k,2}=moments{k,1}; end
        moments{k,1}=.9*moments{k,1}+.1*g{k}; moments{k,2}=.999*moments{k,2}+.001*g{k}.^2;
        v{k}=v{k}-.01*(moments{k,1}/(1-.9^iteration))./(sqrt(moments{k,2}/(1-.999^iteration))+1e-8);
    end
    [W1,b1,W2,b2]=v{:};
end
[a,b]=ndgrid(linspace(-.975,.975,40)); holdout=[a(:)';b(:)'];
pred=tanh(W2*tanh(W1*holdout+b1)+b2);
report=struct('seed',17,'architecture','2-12-tanh-2-tanh','iterations',2500, ...
    'training_samples',size(X,2),'holdout_samples',size(holdout,2), ...
    'label_source','Declared 25 Sugeno rules; synthetic normalized error grid', ...
    'training_mse',loss(end),'holdout_rmse',sqrt(mean((pred-ccmp_fuzzy_rules(holdout)).^2,'all')), ...
    'hardware_training',false,'online_learning',false);
save(fullfile(output,'neural_pid_weights.mat'),'W1','b1','W2','b2','report');
writematrix([(1:numel(loss))' loss],fullfile(output,'neural_training_loss.csv'));
fid=fopen(fullfile(output,'neural_training_report.json'),'w'); fwrite(fid,jsonencode(report,PrettyPrint=true)); fclose(fid);
disp(report);
end
