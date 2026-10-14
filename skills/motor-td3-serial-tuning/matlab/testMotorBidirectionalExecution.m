function report=testMotorBidirectionalExecution(input,output)
% Actual replay parity, range/rate rejection, and true continuous gradients.
arguments
    input (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);c=s.fullHallContract;
c.execution_mode="bidirectional-continuous-step-clamp";
c.execution_mapping_version="bidirectional16-upper8-continuous-relative-step-clamp-v1";
c.host_single_kp_step_limit=.00013556;c.execution_wrapper_required=true;
c.required_firmware_family="v27-bidirectional";c.straight_through_gradient_is_experimental_surrogate=false;
rows=[s.fullHallTrain;s.fullHallValidation];
parts=cellfun(@(r)r.observation(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
parts=cellfun(@(r)r.action_normalized(:),rows,UniformOutput=false);actual=single(cat(2,parts{:}));
[mapped,m]=motorBidirectionalContinuousActionFromObservation(actual,x,c);
assert(max(abs(double(mapped(:)-actual(:))))<1e-6);
physical=reshape(cellfun(@(r)r.actual_target_kp,rows),1,[]);
physicalError=max(abs(m.executed_float32_kp-physical));
% Single-precision normalized observations lose up to one Kp ULP at a slew edge.
% Preserve exact wire gains in replay; do not report normalized recovery as exact.
assert(physicalError<=double(eps(single(max(physical)))));
spec=motorStreamGainSpec(c.stream_gain_profile);requested=single([repmat([spec.action_lower_limit(1) spec.action_upper_limit(1)],1,numel(rows));zeros(1,2*numel(rows))]);
xx=repelem(x,1,2);[bounded,b]=motorBidirectionalContinuousActionFromObservation(requested,xx,c);
assert(all(bounded(2,:)==0) && max(abs(b.executed_float32_kp-b.actual_kp))<=.00013556+1e-9);
assert(all(b.executed_float32_kp>=spec.exact_kp_levels(1)-1e-9 & b.executed_float32_kp<=spec.exact_kp_levels(end)+1e-9));
rejected=0;
for kind=1:5
    a=actual(:,1);state=x(:,1);config=c;
    if kind==1,a(2)=.01;elseif kind==2,a(1)=NaN;
    elseif kind==3,a(1)=spec.action_upper_limit(1)+.1;
    elseif kind==4,state(8)=(.001/.003389-c.state_center(8))/c.state_scale(8);
    else,config.stream_gain_profile="upper8-dense-fullhall";end
    try,motorBidirectionalContinuousActionFromObservation(a,state,config);catch,rejected=rejected+1;end
end
assert(rejected==5);
state=zeros(10,3,'single');state(8,:)=(double(single(.003389))/.003389-c.state_center(8))/c.state_scale(8);
a=dlarray(single([.1 spec.action_lower_limit(1) spec.action_upper_limit(1);0 0 0]),'CB');
gradient=dlfeval(@derivative,a,state,c);g=double(extractdata(gradient));
assert(isequal(g,[1 0 0;0 0 0]));
report=struct(passed=true,actual_replay_rows=numel(rows),actual_float32_gain_reproduction_error=physicalError, ...
    float32_gain_error_at_most_one_ULP=true,exact_wire_gains_preserved_in_replay=true, ...
    range_and_rate_cases=2*numel(rows),invalid_cases_rejected=rejected,continuous_gradient_cases=3, ...
    current_host_step_limit=.00013556,Ki_mask=[1 0],nearest_grid_quantization=false, ...
    surrogate_derivative=false,hardware_accessed=false,Actor_applied=false, ...
    current_v26_runtime_compatible=false,required_firmware_family="v27-bidirectional", ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function g=derivative(a,x,c)
y=motorTD3ExecutedAction(a,x,c,true);g=dlgradient(sum(y(1,:)),a);
end
