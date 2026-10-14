function report=testMotorCriticScreen
m=struct(logged_q_mean=[-.1 -.1],logged_q_std=[0 0], ...
    supported_kp_q_difference_max_abs=[0 0]);
r=screenMotorCriticDiagnostics(m);assert(~r.passed && all(r.constant_state_critics));
m.logged_q_std=[.01 .02];r=screenMotorCriticDiagnostics(m);assert(~r.passed);
m.supported_kp_q_difference_max_abs=[.001 .002];r=screenMotorCriticDiagnostics(m);
assert(r.passed && ~r.deployment_allowed && ~r.performance_claim_allowed);
m.supported_kp_q_difference_max_abs(1)=NaN;assert(~screenMotorCriticDiagnostics(m).passed);
assert(~screenMotorCriticDiagnostics(struct()).passed);
report=struct(passed=true,checks=5,hardware_accessed=false);
end
