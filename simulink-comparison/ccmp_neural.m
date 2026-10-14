function gains = ccmp_neural(u)
% Frozen 2 -> 12 tanh -> 2 tanh network trained on declared fuzzy rule labels.
a=ccmp_assets(); c=ccmp_config(); error=u(2)-u(3);
x=max(-1,min(1,[error/400;(error-u(4))/200]));
y=tanh(a.nn.W2*tanh(a.nn.W1*x+a.nn.b1)+a.nn.b2);
gains=c.baseline.*(1+[.4;.35].*y);
end
