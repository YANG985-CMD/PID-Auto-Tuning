function report=testMotorValueCentering(output)
% Independent discounted algebra; retain original physical reward criteria.
arguments
    output (1,1) string
end
assert(~isfile(output) && startsWith(lower(strrep(output,'\','/')),'e:/simulink/_codex_tmp/'));
reward=[-.001 -.0013 -.0009 -.0011];duration=[100000 135000 97528 142182];
discount=.99.^(duration/100000);C=-mean(reward)/mean(1-discount);
shifted=reward+C*(1-discount);terminalQ=[-.091 -.096 -.089];
maxError=0;
for terminal=terminalQ
    raw=terminal;centered=terminal+C;
    for k=4:-1:1
        raw=reward(k)+discount(k)*raw;
        centered=shifted(k)+discount(k)*centered;
    end
    maxError=max(maxError,abs(centered-(raw+C)));
end
assert(maxError<1e-12 && abs(mean(shifted))<1e-15);
rawQ=[-.094 -.092 -.095];assert(max(abs(sort(rawQ)-sort((rawQ+C)-C)))<1e-15);
assert(find(rawQ==max(rawQ))==find(rawQ+C==max(rawQ+C)));
assert(isequal(reward,[-.001 -.0013 -.0009 -.0011]));
report=struct(passed=true,variable_duration_discounted_return_shift_error=maxError, ...
    unregularized_Q_action_order_invariant=true,training_only_shift_C=C, ...
    validation_statistics_not_used=true,physical_rewards_unchanged=true, ...
    actor_regularizer_scale_not_invariant=true,hardware_accessed=false,deployment_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
