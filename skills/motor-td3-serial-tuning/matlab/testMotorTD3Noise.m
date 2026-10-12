function tests=testMotorTD3Noise
tests=functiontests(localfunctions);
end

function testDefaultsPreserved(testCase)
a=createMotorTD3(7,[1;1],2.5);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.StandardDeviation,sqrt(.2)*[1;1]);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.StandardDeviationMin,[.1;.1]);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.UpperLimit,.5);
end

function testSmallNoiseAndMask(testCase)
a=createMotorTD3(7,[1;0],.25,TargetNoiseStandardDeviation=[.05;.05],TargetNoiseClip=.1);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.StandardDeviation,[.05;0]);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.StandardDeviationMin,[.025;0]);
verifyEqual(testCase,a.AgentOptions.TargetPolicySmoothModel.UpperLimit,.1);
action=getAction(getActor(a),{single(ones(10,1))});
verifyEqual(testCase,action{1}(2),single(0));
verifyEqual(testCase,a.AgentOptions.BatchDataRegularizerOptions.BehaviorCloningRegularizerWeight,.25);
end

function testInvalidNoiseRejected(testCase)
verifyError(testCase,@()createMotorTD3(7,[1;1],2.5, ...
    TargetNoiseStandardDeviation=[NaN;.05]),'MotorTD3:Noise');
verifyError(testCase,@()createMotorTD3(7,[1;1],2.5, ...
    TargetNoiseStandardDeviation=[-.05;.05]),'MotorTD3:Noise');
verifyError(testCase,@()createMotorTD3(7,[1;1],2.5,TargetNoiseClip=0),'MotorTD3:Noise');
end
