function raw=motorFeasibleFractionInverse(absolute,observation,contract)
% Invert actual replay action for verification only; never change replay rows.
[~,m]=motorFeasibleFractionAction(zeros(size(absolute),'single'),observation,contract);
v=double(absolute);mid=(m.lower_absolute_action+m.upper_absolute_action)/2;
q=(v(1,:)-mid)./m.half_feasible_span;
assert(all(isfinite(q)) && all(abs(q)<=1+1e-5) && all(v(2,:)==0));
raw=single([min(1,max(-1,q));zeros(1,size(q,2))]);
end
