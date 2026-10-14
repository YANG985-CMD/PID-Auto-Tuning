function gains = ccmp_fuzzy(u)
c=ccmp_config(); error=u(2)-u(3);
target=ccmp_fuzzy_rules([error/400; (error-u(4))/200]);
gains=c.baseline.*(1+[.4;.35].*target);
end
