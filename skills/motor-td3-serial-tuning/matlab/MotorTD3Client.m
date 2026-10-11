classdef MotorTD3Client < handle
    % Loopback client. Serial port and safety monitor belong to Python bridge.
    properties (SetAccess=private)
        Socket
        Profile
        SimulationOnly
    end
    methods
        function obj = MotorTD3Client(port, tokenFile)
            obj.Socket = tcpclient('127.0.0.1', port, 'Timeout', 20);
            configureTerminator(obj.Socket, 'LF');
            reply = obj.call(struct('op','hello','token',strtrim(fileread(tokenFile))));
            obj.Profile = reply.profile;
            obj.SimulationOnly = reply.simulation_only;
        end
        function result = call(obj, request)
            writeline(obj.Socket, jsonencode(request));
            reply = jsondecode(readline(obj.Socket));
            if ~reply.ok
                error('MotorTD3:BridgeRejected', '%s', reply.error);
            end
            result = reply.result;
        end
        function stop(obj)
            obj.call(struct('op','stop'));
        end
        function result = metadata(obj)
            % Hash and identity for the flushed bridge transition log.
            result = obj.call(struct('op','metadata'));
        end
    end
end
