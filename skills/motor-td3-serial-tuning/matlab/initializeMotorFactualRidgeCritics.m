function [critic1,critic2,report]=initializeMotorFactualRidgeCritics(critic1,critic2,x,a,target,bootIds,center,scale,inputMask,decay,seed)
% Train-only factual ridge priors, with positive Bayesian boot reweighting.
% This is initialization for the custom TD3 experiment, not measured returns.
arguments
    critic1 dlnetwork
    critic2 dlnetwork
    x (10,:) single
    a (2,:) single
    target (1,:) single
    bootIds (:,1) string
    center (42,1) double
    scale (42,1) double
    inputMask (10,1) double
    decay (1,1) double {mustBePositive,mustBeFinite}
    seed (1,1) double {mustBeInteger,mustBeNonnegative}
end
n=size(x,2);assert(size(a,2)==n && numel(target)==n && numel(bootIds)==n);
assert(all(isfinite([x(:);a(:);target(:)])) && all(a(2,:)==0));
assert(all(ismember(inputMask,[0 1])) && all(isfinite([center;scale])) && all(scale>0));
[boots,~,whichBoot]=unique(bootIds);assert(numel(boots)>=2);
f=(motorLocalQuadraticFeatures(x.*single(inputMask),a)-single(center))./single(scale);
D=[double(f)' ones(n,1)];levels=unique(a(1,:));assert(numel(levels)>=3);
penalty=eye(43);penalty(end,end)=0;
stream=RandStream('mt19937ar','Seed',seed+300000);
nets={critic1,critic2};fits=struct([]);coeff=zeros(43,2);
for twin=1:2
    % Positive masses keep every recorded boot/action represented. This is
    % Bayesian reweighting, not a calibrated uncertainty bound.
    masses=-log(max(rand(stream,numel(boots),1),realmin));masses=masses/sum(masses);
    raw=masses(whichBoot);weights=zeros(n,1);
    for level=levels
        ids=a(1,:)==level;weights(ids)=raw(ids)/(numel(levels)*sum(raw(ids)));
    end
    assert(all(weights>0) && abs(sum(weights)-1)<1e-12);
    beta=(D'*(weights.*D)+decay*penalty)\(D'*(weights.*double(target(:))));
    assert(all(isfinite(beta)));
    residual=D*beta-double(target(:));stationarity=D'*(weights.*residual)+decay*penalty*beta;
    assert(norm(stationarity,Inf)<1e-10);
    net=nets{twin};assert(all(net.Learnables.Layer=="q") && height(net.Learnables)==2);
    for k=1:height(net.Learnables)
        if net.Learnables.Parameter(k)=="Weights",net.Learnables.Value{k}=dlarray(single(beta(1:42)'));
        else,net.Learnables.Value{k}=dlarray(single(beta(43)));end
    end
    prediction=double(extractdata(predict(net,dlarray(x,'CB'),dlarray(a,'CB'))))';
    parity=max(abs(prediction-D*beta));assert(parity<1e-7);
    coeff(:,twin)=beta;nets{twin}=net;
    fit=struct(twin=twin,training_boots=boots,positive_boot_masses=masses, ...
        balanced_action_levels=levels,all_training_actions_retained=true, ...
        weighted_training_residual_rmse=sqrt(sum(weights.*residual.^2)), ...
        ridge_objective=sum(weights.*residual.^2)+decay*sum(beta(1:42).^2), ...
        normal_equation_stationarity_inf_norm=norm(stationarity,Inf),network_matrix_parity_error=parity, ...
        coefficients=beta);
    if isempty(fits),fits=fit;else,fits(end+1)=fit;end %#ok<AGROW>
end
critic1=nets{1};critic2=nets{2};distance=norm(coeff(:,1)-coeff(:,2));
assert(distance>0,'MotorTD3:RidgeTwins','Distinct physical-boot priors required');
report=struct(mode="factual-ridge-bootstrap",training_rows=n,training_boots=boots,ridge_coefficient=decay, ...
    local_bootstrap_seed=seed+300000,bootstrap_mode="positive exponential boot masses; actions balanced within masses", ...
    fits=fits,twin_coefficient_distance=distance,validation_data_used=false, ...
    constant_continuation_target_not_actual_return=true,bootstrap_is_calibrated_uncertainty=false, ...
    ridge_initialization_fits=2,gradient_updates=0,hardware_accessed=false,actor_applied=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
end
