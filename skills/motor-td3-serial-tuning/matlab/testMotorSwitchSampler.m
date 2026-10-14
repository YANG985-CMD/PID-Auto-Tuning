function report=testMotorSwitchSampler(input,output)
% Reject rare switch support; synthetic checks do not authorize hardware.
arguments
    input (1,1) string
    output (1,1) string
end
assert(~isfile(output));saved=rng;restore=onCleanup(@()rng(saved)); %#ok<NASGU>
base=double(single(.003389));scale=double(single(.00054224));
levels=double(single([.003389 .00345678 .00352456 .00359234 .00366012]));
source=[];target=[];boots=strings(1,0);
for k=1:5
    other=mod(k,5)+1;if k==5,other=4;end
    for b=1:3
        target=[target repmat(levels(k),1,24)]; %#ok<AGROW>
        source=[source repmat(levels(k),1,20) repmat(levels(other),1,4)]; %#ok<AGROW>
        boots=[boots repmat("train-"+b,1,24)]; %#ok<AGROW>
    end
end
actions=single([(target-base)/scale;zeros(size(target))]);
model=prepareMotorSwitchSampler(actions,source,target,boots);
rng(37);one=sampleMotorSwitchIndices(model,20000);rng(37);two=sampleMotorSwitchIndices(model,20000);
assert(isequal(one,two) && all(one>=1 & one<=numel(source)));
assert(abs(mean(model.changed(one))-4/9)<.02);
for k=1:5,assert(abs(mean(actions(1,one)==model.action_levels(k))-.2)<.015);end
rejected=0;
for kind=1:8
    a=actions;from=source;to=target;ids=boots;
    switchRows=find(model.changed & actions(1,:)==model.action_levels(1));
    if kind==1
        keep=true(size(source));keep(switchRows(2:end))=false;
        a=a(:,keep);from=from(keep);to=to(keep);ids=ids(keep);
    elseif kind==2,ids(switchRows)="one-boot";
    elseif kind==3,a(1,1)=a(1,1)+.1;
    elseif kind==4,from(1)=.1;
    elseif kind==5,from(1)=levels(5);
    elseif kind==6,a(2,1)=.01;
    elseif kind==7,from(1)=NaN;
    else,ids(1)="";end
    try,prepareMotorSwitchSampler(a,from,to,ids);catch,rejected=rejected+1;end
end
assert(rejected==8);
s=load(input);realRejected=false;
try
    rows=s.fullHallTrain;v=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);
    prepareMotorSwitchSampler(cat(2,v{:}),cellfun(@(r)r.actual_source_kp,rows), ...
        cellfun(@(r)r.actual_target_kp,rows),string(cellfun(@(r)r.boot_id,rows,UniformOutput=false)));
catch err,realRejected=strcmp(err.identifier,'MotorTD3:SwitchSamplingSupport');end
assert(realRejected);
report=struct(passed=true,synthetic_draws=20000,deterministic_random_stream=true, ...
    only_real_training_indices_sampled=true,observed_switch_fraction=mean(model.changed(one)), ...
    expected_switch_fraction=4/9,invalid_and_sparse_cases_rejected=rejected, ...
    current_real_data_rejected_for_sparse_switch_groups=realRejected, ...
    new_gradient_updates=0,new_physical_windows=0,hardware_accessed=false, ...
    actor_applied=false,candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
