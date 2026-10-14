function report=testMotorStationaryActors(studies)
% Check actual function-layer masks/range, no hardware or plant simulation.
arguments
    studies (:,1) string
end
results=cell(numel(studies)*3,1);index=0;
for folder=studies'
    study=jsondecode(fileread(fullfile(folder,'training-summary.json')));
    for seed=[7 17 27]
        file=fullfile(folder,"candidate-seed-"+seed+".mat");s=load(file,'experimentalAgent','contract');
        assert(isequal(s.contract.actor_input_mask,[1 1 1 1 1 1 1 0 1 0]));
        rng(991+seed);obs=single(rand(10,128)*10-5);other=obs;
        other([8 10],:)=-other([8 10],:);
        actor=getActor(s.experimentalAgent);a=getAction(actor,{obs});b=getAction(actor,{other});
        assert(isequal(a{1},b{1}),'Mask did not suppress Kp/time copying');
        lower=0;
        if isfield(s.contract,'stream_gain_profile')
            spec=motorStreamGainSpec(string(s.contract.stream_gain_profile));lower=spec.action_lower_limit(1);
        end
        assert(all(a{1}(1,:)>=lower & a{1}(1,:)<=.5) && all(a{1}(2,:)==0));
        assert(s.experimentalAgent.ExperienceBuffer.Length==study.training_experiences);
        exportMotorTD3DiagnosticJSON(file,fullfile(folder,"networks-seed-"+seed+".json"));
        index=index+1;results{index}=struct(seed=seed,checkpoint_sha256=motorFileSHA256(file), ...
            mask_invariance_passed=true,action_range_passed=true,ki_mask_passed=true, ...
            reloaded_experience_buffer_count=study.training_experiences,generated_mcu_code=false);
    end
end
report=struct(passed=true,checkpoints=[results{:}],random_observations_per_checkpoint=128, ...
    hardware_accessed=false,physical_performance_verified=false,deployment_allowed=false);
disp(jsonencode(report));
end
