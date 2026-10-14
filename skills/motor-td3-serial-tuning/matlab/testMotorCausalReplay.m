function tests=testMotorCausalReplay
tests=functiontests(localfunctions);
end

function replay=fixture
r=struct(observation=ones(10,1),next_observation=ones(10,1)*1.01, ...
    state=[0;0;0;0;0;0;0;double(single(.003389));double(single(.00144));0], ...
    action_applied=double(single([.003389;.001476])),action_normalized=[0;.25],reward=-.01);
r.action_normalized=(r.action_applied-r.state(8:9))./[.00027112;.000144];
replay=struct(train={{r;r}},validation={{r}},summary=struct);
end

function testAbsoluteTargetsPreserveGainsAndDelta(testCase)
r=fixture;[a,c]=prepareMotorCausalReplay(r,"absolute-target",false);
verifyEqual(testCase,a.train{1}.physical_delta_action,r.train{1}.action_normalized);
verifyEqual(testCase,c.encoded_baseline_gains(:)+a.train{1}.action_normalized.*c.gain_step_scale(:),r.train{1}.action_applied);
verifyEqual(testCase,a.train{1}.reward,r.train{1}.reward);
verifyFalse(testCase,c.runtime_compatible);
end

function testNormalizerIgnoresValidation(testCase)
r=fixture;r.validation{1}.observation=ones(10,1)*4;
[a,c]=prepareMotorCausalReplay(r,"delta",true);
verifyEqual(testCase,c.state_center,ones(1,10));
verifyEqual(testCase,c.state_scale,.01*ones(1,10));
verifyEqual(testCase,a.train{1}.observation,zeros(10,1));
verifyEqual(testCase,a.validation{1}.observation,5*ones(10,1));
end

function testHoldTargetStillHasZeroPhysicalChange(testCase)
r=fixture;r.train{1}.state(9)=r.train{1}.action_applied(2);
r.train{1}.action_normalized=[0;0];
[a,~]=prepareMotorCausalReplay(r,"absolute-target",false);
verifyEqual(testCase,a.train{1}.physical_delta_action,[0;0]);
verifyGreaterThan(testCase,a.train{1}.action_normalized(2),.24);
end
