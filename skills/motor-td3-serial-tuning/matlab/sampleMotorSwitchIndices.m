function ids=sampleMotorSwitchIndices(model,batchSize)
arguments
    model struct
    batchSize (1,1) double {mustBeInteger,mustBePositive}=32
end
group=randi(numel(model.groups),1,batchSize);ids=zeros(1,batchSize);
for k=1:batchSize
    g=model.groups{group(k)};status=1+(rand<g.switch_probability);
    boots=g.indices{status};rows=boots{randi(numel(boots))};ids(k)=rows(randi(numel(rows)));
end
assert(all(ids>=1 & ids<=model.training_rows));
end
