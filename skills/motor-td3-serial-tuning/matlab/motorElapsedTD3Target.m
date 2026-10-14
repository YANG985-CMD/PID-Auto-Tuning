function target=motorElapsedTD3Target(reward,nextQ1,nextQ2,elapsedUs,done)
% Per-transition discount with a declared .99 per100ms time basis.
assert(isequal(size(reward),size(nextQ1),size(nextQ2),size(elapsedUs),size(done)));
assert(all(isfinite([reward(:);nextQ1(:);nextQ2(:);elapsedUs(:);done(:)])));
assert(all(elapsedUs(:)>0) && all(ismember(done(:),[0 1])));
discount=.99.^(double(elapsedUs)/100000);
target=single(double(reward)+(1-double(done)).*discount.*min(double(nextQ1),double(nextQ2)));
end
