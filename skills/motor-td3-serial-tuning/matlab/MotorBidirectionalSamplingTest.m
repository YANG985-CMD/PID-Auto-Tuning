classdef MotorBidirectionalSamplingTest < matlab.unittest.TestCase
    % Fixtures validate admission only and are never saved as motor evidence.
    methods (Test)
        function qualifiedNineTargets(test)
            [a,s,t,b]=test.fixture();m=prepareMotorBidirectionalSwitchSampler(a,s,t,b);
            test.verifyNumElements(m.groups,9);
            test.verifyEqual([m.report.groups.hold_rows],4*ones(1,9));
            test.verifyEqual([m.report.groups.switch_boots],2*ones(1,9));
            test.verifyFalse(m.report.new_physical_evidence_created);
        end
        function oneBootIsRejected(test)
            [a,s,t,b]=test.fixture();b(:)="fixture-only-one";
            test.verifyError(@()prepareMotorBidirectionalSwitchSampler(a,s,t,b),'MotorTD3:SwitchSamplingSupport');
        end
        function noSwitchIsRejected(test)
            [a,s,t,b]=test.fixture();s=t;
            test.verifyError(@()prepareMotorBidirectionalSwitchSampler(a,s,t,b),'MotorTD3:SwitchSamplingSupport');
        end
        function missingMeasuredTargetIsRejected(test)
            [a,s,t,b]=test.fixture();
            test.verifyError(@()prepareMotorBidirectionalSwitchSampler(a(:,9:end),s(9:end),t(9:end),b(9:end)), ...
                'MotorTD3:BidirectionalTargets');
        end
        function onlyRealIndicesReturned(test)
            [a,s,t,b]=test.fixture();m=prepareMotorBidirectionalSwitchSampler(a,s,t,b);
            rng(7);ids=sampleMotorSwitchIndices(m,2000);
            test.verifyGreaterThanOrEqual(min(ids),1);test.verifyLessThanOrEqual(max(ids),72);
            test.verifyNumElements(unique(ids),72);
        end
    end
    methods (Static)
        function [a,s,t,b]=fixture()
            gains=double(single([.002856927 .002989098 .003121269 .00325344 .003389 .00345678 .00352456 .00359234 .00366012]));
            t=repelem(gains,8);s=t;
            switched=reshape(5:8,[],1)+(0:8)*8;
            neighbors=[2:9 8];s(switched)=repelem(gains(neighbors),4);
            a=single([(t-double(single(.003389)))/double(single(.00054224));zeros(1,72)]);
            b=repmat(["fixture-a" "fixture-a" "fixture-b" "fixture-b"],1,18);
        end
    end
end
