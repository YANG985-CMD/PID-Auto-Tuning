function model=prepareMotorBidirectionalSwitchSampler(actions,source,target,boots)
% Experimental capped reweighting of real training rows, never new evidence.
actions=single(actions);source=double(source(:)');target=double(target(:)');boots=string(boots(:)');
assert(size(actions,1)==2 && size(actions,2)==numel(source) && numel(target)==numel(source) && numel(boots)==numel(source));
assert(all(isfinite(actions),'all') && all(isfinite(source)) && all(isfinite(target)) && all(strlength(boots)>0));
assert(all(actions(2,:)==0));
baseline=double(single(.003389));gainScale=double(single(.00054224));
assert(max(abs(baseline+gainScale*double(actions(1,:))-target))<1e-9);
assert(all(source>=double(single(.002856927))-1e-9 & source<=double(single(.00366012))+1e-9));
assert(all(target>=double(single(.002856927))-1e-9 & target<=double(single(.00366012))+1e-9));
assert(all(abs(target-source)<=.00013556+1e-9));
expected=double(single([.002856927 .002989098 .003121269 .00325344 .003389 .00345678 .00352456 .00359234 .00366012]));
assert(isequal(unique(target),expected),'MotorTD3:BidirectionalTargets','Require all nine actually held targets; allowed interpolation is not measured support');
levels=unique(actions(1,:));assert(numel(levels)==9);
changed=source~=target;groups=cell(1,numel(levels));status=struct([]);
for k=1:numel(levels)
    at=actions(1,:)==levels(k);g=struct;g.indices=cell(1,2);
    counts=zeros(1,2);bootCounts=counts;
    for state=1:2
        ids=find(at & changed==(state==2));counts(state)=numel(ids);uniqueBoots=unique(boots(ids));bootCounts(state)=numel(uniqueBoots);
        assert(counts(state)>=4 && bootCounts(state)>=2,'MotorTD3:SwitchSamplingSupport', ...
            'Every target/hold-or-switch group needs >=4 real rows from >=2 training boots; reweighting cannot create coverage');
        g.indices{state}=arrayfun(@(b)ids(boots(ids)==b),uniqueBoots,UniformOutput=false);
    end
    g.switch_probability=4*counts(2)/(counts(1)+4*counts(2));groups{k}=g;
    value=struct(action_normalized=double(levels(k)),hold_rows=counts(1),switch_rows=counts(2), ...
        hold_boots=bootCounts(1),switch_boots=bootCounts(2),switch_probability=g.switch_probability);
    if isempty(status),status=value;else,status(end+1)=value;end %#ok<AGROW>
end
model=struct(groups={groups},action_levels=levels,changed=changed,training_rows=numel(source), ...
    report=struct(mode="bidirectional-balanced-actions-switch-cap4",switch_reweight_multiplier=4, ...
        minimum_unique_rows_per_group=4,minimum_boots_per_group=2,groups=status, ...
        within_status_boots_balanced=true,new_physical_evidence_created=false, ...
        guard_is_sampling_qualification_not_performance_or_safety=true));
end
