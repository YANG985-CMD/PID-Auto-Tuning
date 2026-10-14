function gains = ccmp_guard(u)
% Identical absolute and per-decision gain guards for every tuning method.
c=ccmp_config(); candidate=u(1:2); previous=u(3:4);
if any(~isfinite(candidate)), candidate=previous; end
gains=max(c.lower,min(c.upper,candidate));
gains=previous+max(-c.step,min(c.step,gains-previous));
end
