function spec=motorStreamGainSpec(profile)
% Exact experiment support; neural action bounds do not authorize hardware.
arguments
    profile (1,1) string {mustBeMember(profile,["two","interior3","lower4","lower8","lower8-sampling","lower16-fullhall","lower16-upper4-fullhall","switching-local4-fullhall","upper8-fullhall","upper8-dense-fullhall","bidirectional16-upper8-fullhall"])}
end
allowed=[.003389 .00352456];lower=0;
if profile=="interior3",allowed=[.003389 .00345678 .00352456];end
if profile=="lower4",allowed=[.00325344 .003389 .00345678 .00352456];lower=-.5;end
if profile=="lower8",allowed=[.003121269 .00325344 .003389 .00345678 .00352456];lower=-1;end
upper=.5;
if profile=="lower8-sampling",allowed=[.003121269 .00325344 .003389];lower=-1;upper=0;end
if profile=="lower16-fullhall"
    allowed=[.002856927 .003121269 .003389];
    lower=(double(single(allowed(1)))-double(single(.003389)))/double(single(.00054224));upper=0;
end
if profile=="lower16-upper4-fullhall"
    allowed=[.002856927 .003121269 .003389 .00352456];
    lower=(double(single(allowed(1)))-double(single(.003389)))/double(single(.00054224));
    upper=(double(single(allowed(end)))-double(single(.003389)))/double(single(.00054224));
end
if profile=="switching-local4-fullhall"
    allowed=[.00325344 .003389 .00352456];
    lower=(double(single(allowed(1)))-double(single(.003389)))/double(single(.00054224));
    upper=(double(single(allowed(end)))-double(single(.003389)))/double(single(.00054224));
end
if profile=="upper8-fullhall"
    allowed=[.003389 .00352456 .00366012];lower=0;
    upper=(double(single(allowed(end)))-double(single(.003389)))/double(single(.00054224));
end
if profile=="upper8-dense-fullhall"
    allowed=.003389*(1+(0:8)/100);lower=0;
    upper=(double(single(allowed(end)))-double(single(.003389)))/double(single(.00054224));
end
if profile=="bidirectional16-upper8-fullhall"
    allowed=sort([.002856927 .002989098 .003121269 .00325344 .003389*(1+(0:8)/100)]);
    lower=(double(single(allowed(1)))-double(single(.003389)))/double(single(.00054224));
    upper=(double(single(allowed(end)))-double(single(.003389)))/double(single(.00054224));
end
spec=struct(exact_kp_levels=double(single(allowed)),fixed_ki=double(single(.00144)), ...
    action_lower_limit=[lower -1],action_upper_limit=[upper 1], ...
    output_scale=[(upper-lower)/2 1],output_bias=[(upper+lower)/2 0], ...
    action_mask=[1 0],deployment_allowed=false);
end
