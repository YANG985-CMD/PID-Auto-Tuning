function gains = ccmp_ai(u)
% External Codex workflow interface: replay an explicit approved gain plan.
% u = [seconds, reference, rpm, error20ms, error40ms, iqRef, phasePeak, Kp, Ki].
a=ccmp_assets(); index=find(a.plan(:,1)<=u(1)+1e-9,1,'last');
if isempty(index), index=1; end
gains=a.plan(index,2:3)';
end
