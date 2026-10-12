function server = startSpeedLoopShadowServer(checkpoint, tokenFile, port)
% Start the local MATLAB TD3 shadow server used by the motor bridge.
% The returned object must remain in the MATLAB workspace while the bridge runs.
arguments
    checkpoint (1,1) string
    tokenFile (1,1) string
    port (1,1) double {mustBeInteger,mustBePositive}
end
server = SpeedLoopShadowServer(checkpoint, tokenFile, port);
fprintf("MATLAB shadow server listening on 127.0.0.1:%d (%s)\n", ...
    server.Socket.ServerPort, server.PolicyVersion);
end
