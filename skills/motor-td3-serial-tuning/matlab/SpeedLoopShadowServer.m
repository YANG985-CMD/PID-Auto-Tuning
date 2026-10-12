classdef SpeedLoopShadowServer < handle
    % Fixed, warmed TD3 Actor on loopback. Suggestions only; no device I/O.
    properties (SetAccess=private)
        Socket
        Actor
        CheckpointSHA
        PolicyVersion = "experimental-shadow-20261012-kp-only"
        PredictionCount = 0
        RejectionCount = 0
    end
    properties (Access=private)
        Token
        LastBoot = ""
        LastSeq = 0
        LastTime = 0
    end
    methods
        function obj = SpeedLoopShadowServer(checkpoint, tokenFile, port)
            expected = "2d9516d757ad8e9784da9171afe48f5dc60f809666639084c691bbc10b23efab";
            obj.CheckpointSHA = obj.sha256(checkpoint);
            assert(obj.CheckpointSHA==expected,'MotorTD3:Checkpoint','Unreviewed checkpoint');
            loaded = load(checkpoint,'agent','report');
            assert(loaded.report.replay_experiences==134 && loaded.report.td3_training_performed);
            assert(~loaded.report.deployment_allowed && ~loaded.report.ki_exploration_performed);
            obj.Actor = getActor(loaded.agent); % Actor avoids exploration noise.
            obj.Token = strtrim(string(fileread(tokenFile)));
            assert(strlength(obj.Token)>=64,'MotorTD3:Token','Use a fresh private token');
            for k=1:20, getAction(obj.Actor,{zeros(10,1,'single')}); end
            obj.Socket = tcpserver('127.0.0.1',port,'Timeout',0.2);
            configureTerminator(obj.Socket,'LF');
            obj.Socket.ConnectionChangedFcn = @(~,~) obj.newConnection();
            configureCallback(obj.Socket,'terminator',@(src,~) obj.receive(src));
        end
        function close(obj)
            if ~isempty(obj.Socket)
                configureCallback(obj.Socket,'off');
                obj.Socket.ConnectionChangedFcn=[];
                obj.Socket=[];
            end
        end
        function delete(obj)
            obj.close();
        end
    end
    methods (Access=private)
        function newConnection(obj)
            obj.LastBoot=""; obj.LastSeq=0; obj.LastTime=0;
        end
        function receive(obj,src)
            requestId=0;
            try
                line=readline(src);
                assert(strlength(line)<=8192,'MotorTD3:Frame','Oversized request');
                req=jsondecode(line); requestId=req.request_id;
                assert(isscalar(requestId) && requestId>=1 && fix(requestId)==requestId);
                assert(string(req.token)==obj.Token,'MotorTD3:Auth','Authentication failed');
                assert(req.schema_version==1 && req.shadow_only && ~req.hardware_writeback);
                if string(req.op)=="hello"
                    result=struct(policy_version=obj.PolicyVersion,checkpoint_sha256=obj.CheckpointSHA, ...
                        state_scale=[1000 1000 1000 1000 3 2 24 .003389 .00144 3000], ...
                        shadow_only=true,hardware_writeback=false,training_performed=false);
                else
                    assert(string(req.op)=="predict");
                    t=req.telemetry;
                    assert(string(req.firmware_id)=="g431-speedloop-pi-motion-v5");
                    assert(t.fault==0 && isscalar(t.seq) && t.seq>=1 && fix(t.seq)==t.seq);
                    assert(t.t_us>=0 && fix(t.t_us)==t.t_us);
                    assert(~isempty(regexp(char(t.boot_id),'^[0-9a-f]{16}$','once')));
                    assert(obj.LastBoot=="" || obj.LastBoot==string(t.boot_id));
                    assert(t.seq>obj.LastSeq && t.t_us>obj.LastTime);
                    raw=[t.speed_ref t.speed t.speed_ref-t.speed t.error_history ...
                        t.integral_output t.current t.vbus t.kp t.ki t.elapsed_ms];
                    assert(numel(raw)==10 && all(isfinite(raw)));
                    assert(abs(t.speed)<1800 && t.current>=0 && t.current<2 && t.vbus>=18 && t.vbus<=30);
                    lower=[.0013556 .00072]; upper=[.0054224 .00216]; step=[.00027112 .000144];
                    current=double(single([t.kp t.ki]));
                    assert(all(current>=lower & current<=upper));
                    observation=single(max(-5,min(5,raw./[1000 1000 1000 1000 3 2 24 .003389 .00144 3000])));
                    started=tic;
                    prediction=getAction(obj.Actor,{observation(:)});
                    inferenceMs=toc(started)*1000;
                    action=double(prediction{1}(:)');
                    assert(numel(action)==2 && all(isfinite(action)) && all(abs(action)<=1));
                    lo=max(lower,current-step); hi=min(upper,current+step);
                    distance=current-lo; distance(action>=0)=hi(action>=0)-current(action>=0);
                    original=double(single(current+distance.*action));
                    % No Ki excitation exists in the real dataset. This is a
                    % constrained advisory policy, not the original two-head policy.
                    proposal=[original(1) double(single(.00144))];
                    result=struct(policy_version=obj.PolicyVersion,checkpoint_sha256=obj.CheckpointSHA, ...
                        telemetry_seq=t.seq,t_us=t.t_us,boot_id=string(t.boot_id), ...
                        raw_state=raw,observation=double(observation),raw_action=action, ...
                        original_two_head_gains=original,kp=proposal(1),ki=proposal(2), ...
                        ki_masked=true,inference_ms=inferenceMs,source_enabled=logical(t.enabled), ...
                        shadow_only=true,hardware_writeback=false,deployment_allowed=false, ...
                        motor_run_stage_verified=false,training_performed=false);
                    obj.LastBoot=string(t.boot_id); obj.LastSeq=t.seq; obj.LastTime=t.t_us;
                    obj.PredictionCount=obj.PredictionCount+1;
                end
                reply=struct(ok=true,request_id=requestId,result=result);
            catch ex
                obj.RejectionCount=obj.RejectionCount+1;
                % TCP writeline is ASCII. Localized exception text must not
                % corrupt JSON or expose the private authentication request.
                identifier=string(ex.identifier);
                if identifier=="", identifier="MotorTD3:Rejected"; end
                reply=struct(ok=false,request_id=requestId,error=identifier);
            end
            writeline(src,jsonencode(reply));
        end
    end
    methods (Static, Access=private)
        function hash=sha256(filename)
            fid=fopen(filename,'rb'); assert(fid>=0);
            closer=onCleanup(@() fclose(fid));
            bytes=fread(fid,Inf,'*uint8');
            digest=java.security.MessageDigest.getInstance('SHA-256'); digest.update(bytes);
            hash=string(lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2)',1,[])));
        end
    end
end
