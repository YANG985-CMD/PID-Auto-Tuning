function gains = ccmp_td3(u)
% Real frozen experimental checkpoint, deterministic inference, no exploration.
% Integral input is an algebraic proxy; this simulation is distribution-shifted.
a=ccmp_assets(); c=ccmp_config(); contract=a.td3.learning_contract;
err=u(2)-u(3); integralProxy=u(6)-u(8)*err;
raw=[u(2)/1000;u(3)/1000;err/1000;u(4)/1000;integralProxy/3; ...
    u(7)/2;24/24;u(8)/.003389;u(5)/1000;u(1)*1000/3000];
raw=double(single(max(-5,min(5,raw))));
x=max(-5,min(5,(raw-contract.state_center(:))./contract.state_scale(:)));
x=x.*contract.actor_input_mask(:);
layers=a.td3.actor;
for k=1:3
    name="fc"+k;
    w=find(strcmp({layers.layer},name)&strcmp({layers.parameter},'Weights'));
    b=find(strcmp({layers.layer},name)&strcmp({layers.parameter},'Bias'));
    x=double(layers(w).value)*x+double(layers(b).value(:));
    if k<3, x=max(0,x); else, x=tanh(x); end
end
action=(x.*contract.actor_output_affine_scale(:)+contract.actor_output_affine_bias(:)).*contract.action_mask(:);
gains=contract.encoded_baseline_gains(:)+action.*contract.gain_step_scale(:);
% The original real-data experiment supported only these absolute Kp targets.
levels=double(single([.003121269 .00325344 .003389]));
[~,nearest]=min(abs(levels-gains(1))); gains(1)=levels(nearest);
gains(2)=c.baseline(2);
end
