function action=motorTD3ExecutedAction(raw,observation,contract,gradientRequired)
arguments
    raw
    observation
    contract struct
    gradientRequired (1,1) logical=false
end
mode=string(contract.execution_mode);
if mode=="upper8-exact-grid-straight-through"
    action=motorUpper8ActionFromObservation(raw,observation,contract,gradientRequired);
elseif mode=="upper8-continuous-step-clamp"
    action=motorUpper8ContinuousActionFromObservation(raw,observation,contract);
elseif mode=="bidirectional-continuous-step-clamp"
    action=motorBidirectionalContinuousActionFromObservation(raw,observation,contract);
elseif mode=="bidirectional-feasible-fraction"
    action=motorFeasibleFractionAction(raw,observation,contract);
else
    error('MotorTD3:ExecutionMode','No execution wrapper for this mode');
end
end
