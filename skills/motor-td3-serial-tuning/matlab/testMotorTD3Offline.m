function tests=testMotorTD3Offline
tests=functiontests(localfunctions);
end

function testMaskIsInsideActorAndNoise(testCase)
agent=createMotorTD3(7,[1;0]);
a=getAction(getActor(agent),{single(ones(10,4))});
verifyEqual(testCase,a{1}(2,:),zeros(1,4,'single'));
verifyEqual(testCase,agent.AgentOptions.TargetPolicySmoothModel.StandardDeviation(2),0);
verifyEqual(testCase,agent.AgentOptions.ExplorationModel.StandardDeviation(2),0);
end

function testNativeBehaviorRegularizer(testCase)
agent=createMotorTD3(7,[1;1],2.5);
verifyEqual(testCase,agent.AgentOptions.BatchDataRegularizerOptions.BehaviorCloningRegularizerWeight,2.5);
end

function testSHAUsesFileBytes(testCase)
verifyEqual(testCase,strlength(motorFileSHA256(which('createMotorTD3'))),64);
end

function testInvalidMaskRejected(testCase)
verifyError(testCase,@()createMotorTD3(7,[0;1]),'MATLAB:assertion:failed');
end

function testAppliedKiCannotBeRelabeled(testCase)
verifyError(testCase,@()motorTD3MaskedAction([0;.25],[1;0]),'MotorTD3:MaskConflict');
verifyEqual(testCase,motorTD3MaskedAction([-.2;.25],[1;1]),[-.2;.25]);
end

function testMaskAfterNativeGradientUpdates(testCase)
agent=createMotorTD3(7,[1;0],2.5);
for k=1:128
    s=single(ones(10,1)*(1+k/1000));
    e=struct('Observation',{{s}},'Action',{{single([.1;0])}}, ...
        'Reward',-.01,'NextObservation',{{s+.01}},'IsDone',0);
    append(agent.ExperienceBuffer,e);
end
stats=trainFromData(agent,rlTrainingFromDataOptions('MaxEpochs',1, ...
    'NumStepsPerEpoch',8,'Plots','none','Verbose',false,'SaveAgentCriteria','none'));
verifyEqual(testCase,double(stats.TotalSteps(end)),8);
a=getAction(getActor(agent),{single(ones(10,4))});
verifyEqual(testCase,reshape(a{1},2,[]), ...
    [reshape(a{1}(1,:,:),1,[]);zeros(1,4,'single')]);
end

function testBatchedDiagnostics(testCase)
agent=createMotorTD3(7);
r=struct(observation=ones(10,1),next_observation=ones(10,1), ...
    action_normalized=[0;0],reward=-.01,boot_id="test-only",telemetry_seq_start=1);
result=diagnoseMotorTD3Policy(agent,{r;r;r});
verifySize(testCase,result.metrics.action_mean,[1 2]);
verifyEqual(testCase,height(result.predictions),3);
verifyFalse(testCase,result.metrics.metrics_are_physical_performance);
end
