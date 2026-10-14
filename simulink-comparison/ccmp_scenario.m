function [speed,load] = ccmp_scenario(name)
% Independent construction/tuning scenario and a common heldout scenario.
if nargin==0, name="comparison"; end
switch string(name)
    case "comparison"
        speed=timeseries([0;1000;1000;1200;1200;800;800],[0;.05;2;2.001;4;4.001;6]);
        load=timeseries([0;.012;.012;.025;.025;0;0],[0;1.5;2.999;3;4.999;5;6]);
    case "tuning"
        speed=timeseries([0;900;900;1100;1100],[0;.05;1.2;1.201;2.5]);
        load=timeseries([0;.01;.01;0;0],[0;.8;1.799;1.8;2.5]);
    otherwise
        error('Comparison:Scenario','Unknown scenario');
end
speed=setinterpmethod(speed,'zoh'); load=setinterpmethod(load,'zoh');
end
