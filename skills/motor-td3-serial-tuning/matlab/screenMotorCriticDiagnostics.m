function report=screenMotorCriticDiagnostics(metrics)
% Detect numerically constant critics. This cannot establish policy performance.
required=["logged_q_mean","logged_q_std","supported_kp_q_difference_max_abs"];
present=all(isfield(metrics,required));
report=struct(passed=false,constant_state_critics=[],constant_action_critics=[], ...
    deployment_allowed=false,performance_claim_allowed=false, ...
    interpretation="Numerical non-collapse is necessary only; no counterfactual plant or stability evidence");
if ~present,report.reason="Missing critic sensitivity diagnostics";return;end
meanQ=metrics.logged_q_mean(:);stateStd=metrics.logged_q_std(:);
actionSpan=metrics.supported_kp_q_difference_max_abs(:);
if numel(meanQ)~=2 || numel(stateStd)~=2 || numel(actionSpan)~=2 || ...
        any(~isfinite([meanQ;stateStd;actionSpan])) || any([stateStd;actionSpan]<0)
    report.reason="Invalid critic sensitivity diagnostics";return;
end
resolution=32*double(eps(single(max(abs(meanQ),1e-4))));
report.constant_state_critics=(stateStd<=resolution)';
report.constant_action_critics=(actionSpan<=resolution)';
report.numeric_resolution=resolution';
report.passed=~any(report.constant_state_critics | report.constant_action_critics);
if report.passed,report.reason="Both critics retain state and local-action sensitivity";
else,report.reason="Constant state or action response; reject this diagnostic candidate";end
end
