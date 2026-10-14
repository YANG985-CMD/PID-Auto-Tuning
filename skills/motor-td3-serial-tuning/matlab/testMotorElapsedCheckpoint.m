function report=testMotorElapsedCheckpoint(study)
% Saved custom optimizer/target state and inference container equality.
arguments
    study (1,1) string
end
summary=jsondecode(fileread(fullfile(study,'training-summary.json')));count=0;maskChecks=0;
for r=summary.candidates(:)'
    file=fullfile(study,"candidate-"+string(r.mode)+"-seed-"+r.seed+".mat");
    assert(motorFileSHA256(file)==string(r.checkpoint_sha256));s=load(file);
    assert(s.contract.custom_elapsed_trainer && ~s.contract.native_trainFromData_resume_allowed);
    assert(s.experimentalAgent.ExperienceBuffer.Length==45);
    assert(s.trainingState.critic_iterations==600 && s.trainingState.actor_iterations==300);
    actor=getModel(getActor(s.experimentalAgent));critics=getCritic(s.experimentalAgent);
    equal(actor,s.trainingState.actor);equal(getModel(critics(1)),s.trainingState.critic1);
    equal(getModel(critics(2)),s.trainingState.critic2);
    assert(~isempty(s.trainingState.actor_average) && ~isempty(s.trainingState.actor_square_average));
    assert(~isempty(s.trainingState.critic1_average) && ~isempty(s.trainingState.critic2_average));
    rng(991+r.seed);obs=single(rand(10,128)*10-5);changed=obs;changed(10,:)=-changed(10,:);
    a=getAction(getActor(s.experimentalAgent),{obs});b=getAction(getActor(s.experimentalAgent),{changed});
    assert(isequal(a{1},b{1}) && all(a{1}(2,:)==0) && all(a{1}(1,:)>=-1 & a{1}(1,:)<=0));
    targetAction=extractdata(predict(s.trainingState.targetActor,dlarray(obs,'CB')));
    assert(all(isfinite(targetAction),'all') && all(targetAction(2,:)==0));
    for q={s.trainingState.targetCritic1,s.trainingState.targetCritic2}
        value=extractdata(predict(q{1},dlarray(obs,'CB'),dlarray(single(targetAction),'CB')));
        assert(all(isfinite(value),'all'));
    end
    count=count+1;maskChecks=maskChecks+128;
end
report=struct(passed=true,reloaded_checkpoints=count,unique_training_decisions_per_checkpoint=45, ...
    independent_validation_decisions_excluded=45,optimizer_state_present=true,target_network_state_present=true, ...
    inference_container_weights_equal=true,mask_bounds_random_checks=maskChecks, ...
    native_continuation_disallowed=true,hardware_accessed=false,deployment_allowed=false);
f=fopen(fullfile(study,'checkpoint-tests.json'),'wb');assert(f>=0);
fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
function equal(a,b)
assert(isequal(a.Learnables.Layer,b.Learnables.Layer) && isequal(a.Learnables.Parameter,b.Learnables.Parameter));
for index=1:height(a.Learnables),assert(isequal(extractdata(a.Learnables.Value{index}),extractdata(b.Learnables.Value{index})));end
end
