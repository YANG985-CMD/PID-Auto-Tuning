function phi=motorGainDeltaQuadraticFeatures(x,a,sourceGainAffine)
% Q basis centered on the recorded source gain; Actor action stays absolute.
% sourceGainAffine maps state component 8 to the source normalized target.
u=a(1,:)-single(sourceGainAffine(1))*x(8,:)-single(sourceGainAffine(2));
phi=[x;x.^2;u;u.^2;x.*u;x.*u.^2];
end
