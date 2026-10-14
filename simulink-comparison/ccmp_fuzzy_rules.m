function target = ccmp_fuzzy_rules(x)
% Zero-order Sugeno inference; five triangular error/change sets, 25 rules.
% x columns = error/400rpm, (error-error20ms)/200rpm. Clipped to [-1,1].
x=max(-1,min(1,x)); centers=[-1 -.5 0 .5 1];
target=zeros(2,size(x,2));
for n=1:size(x,2)
    me=max(0,1-abs(x(1,n)-centers)/.5);
    md=max(0,1-abs(x(2,n)-centers)/.5);
    weight=me(:)*md(:)';
    kpRule=zeros(5); kiRule=zeros(5);
    for i=1:5
        for j=1:5
            kpRule(i,j)=max(-1,min(1,.9*abs(centers(i))+.2*centers(i)*centers(j)-.15));
            kiRule(i,j)=max(-1,min(1,.65*(1-abs(centers(i)))-.5*abs(centers(j))-.25));
        end
    end
    target(:,n)=[sum(weight.*kpRule,'all'); sum(weight.*kiRule,'all')]/sum(weight,'all');
end
end
