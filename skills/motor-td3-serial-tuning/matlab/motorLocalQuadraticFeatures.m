function phi=motorLocalQuadraticFeatures(x,a)
% Local smooth action basis; coefficients may have either curvature sign.
u=a(1,:);
phi=[x;x.^2;u;u.^2;x.*u;x.*u.^2];
end
