function action=motorTD3MaskedAction(actual,mask)
% Reject incompatible physical actions; never relabel them as hold-gains.
arguments
    actual (2,1) double
    mask (2,1) double
end
assert(all(ismember(mask,[0 1])) && mask(1)==1);
assert(all(isfinite(actual)) && all(abs(actual)<=1+1e-6));
assert(all(abs(actual(mask==0))<1e-7),'MotorTD3:MaskConflict', ...
    'Inactive action channel has physical nonzero actions');
action=actual;
end
