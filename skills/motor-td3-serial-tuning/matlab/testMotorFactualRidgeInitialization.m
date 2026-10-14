function report=testMotorFactualRidgeInitialization(input,replay,output)
arguments
    input (1,1) string
    replay (1,1) string
    output (1,1) string
end
assert(~isfolder(output));mkdir(output);s=load(input);c=s.fullHallContract;rows=s.fullHallTrain;
x=matrix(rows,'observation');a=matrix(rows,'action_normalized');dt=cellfun(@(r)r.duration_us,rows)';
reward=cellfun(@(r)r.reward,rows)';C=-mean(reward)/(1-mean(.99.^(dt/100000)));
target=single(reward+C*(1-.99.^(dt/100000)));
mask=c.critic_input_mask(:);features=double(motorLocalQuadraticFeatures(x.*single(mask),a));
center=mean(features,2);scale=max(std(features,0,2),1e-3);
boots=string(cellfun(@(r)r.boot_id,rows,UniformOutput=false));
agent=createMotorTD3(7,[1;0],0,CriticInitialValue=0,CriticInputMask=mask, ...
    CriticArchitecture="local-quadratic",CriticFeatureCenter=center,CriticFeatureScale=scale);
q=getCritic(agent);q1=getModel(q(1));q2=getModel(q(2));before=rng;
[first,second,fit]=initializeMotorFactualRidgeCritics(q1,q2,x,a,target,boots(:),center,scale,mask,.01,7);
assert(isequal(before,rng));
permutation=size(x,2):-1:1;
[reordered,~,~]=initializeMotorFactualRidgeCritics(q1,q2,x(:,permutation),a(:,permutation),target(permutation), ...
    boots(permutation),center,scale,mask,.01,7);
permutationError=distance(first,reordered);assert(permutationError<1e-8 && distance(first,second)>0);
badKi=a;badKi(2,1)=.1;rejected=false;
try,initializeMotorFactualRidgeCritics(q1,q2,x,badKi,target,boots(:),center,scale,mask,.01,7);catch,rejected=true;end
assert(rejected);oneBootRejected=false;
try,initializeMotorFactualRidgeCritics(q1,q2,x,a,target,repmat("one",numel(boots),1),center,scale,mask,.01,7);catch,oneBootRejected=true;end
assert(oneBootRejected);
% Compare the explicit historical coordinate to the preserved old trainer.
legacy=trainMotorFullHallTD3LegacyInit(input,replay,fullfile(output,'legacy'),2, ...
    Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="range-midpoint", ...
    ActorGainFeature="observed",RequireMeasuredSwitches=true,ValueCentering=true, ...
    CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5,TrainingSeedMode="isolated-update-stream");
current=trainMotorFullHallTD3(input,replay,fullfile(output,'historical-mode'),2, ...
    Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="range-midpoint", ...
    ActorGainFeature="observed",RequireMeasuredSwitches=true,ValueCentering=true, ...
    CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5, ...
    TrainingSeedMode="isolated-update-stream",ActorLambdaCoordinates="native");
warm=trainMotorFullHallTD3(input,replay,fullfile(output,'warm-corrected'),2, ...
    Sampling="balanced-actual-actions",RewardModes="complete-Hall",Initialization="range-midpoint", ...
    ActorGainFeature="observed",RequireMeasuredSwitches=true,ValueCentering=true, ...
    CriticArchitecture="local-quadratic",CriticWeightDecay=.01,CriticLearningRate=1e-5, ...
    TrainingSeedMode="isolated-update-stream",CriticInitialization="factual-ridge-bootstrap");
legacyError=0;
for seed=[7 17 27]
    name="candidate-complete-Hall-seed-"+seed+".mat";
    old=load(fullfile(output,'legacy',name),'trainingState');new=load(fullfile(output,'historical-mode',name),'trainingState');
    for field=["actor","critic1","critic2","targetActor","targetCritic1","targetCritic2"]
        legacyError=max(legacyError,distance(old.trainingState.(field),new.trainingState.(field)));
    end
    assert(isequal(old.trainingState.rng_state,new.trainingState.rng_state));
end
assert(legacyError<1e-8 && warm.critic_update_iterations==6 && warm.actor_updates==3);
for candidate=warm.candidates(:)'
    assert(candidate.critic_initialization=="factual-ridge-bootstrap");
    assert(candidate.actor_lambda_value_coordinates=="unshifted-physical");
    assert(~candidate.critic_initialization_report.validation_data_used);
    assert(isequal(sort(candidate.critic_initialization_report.training_boots),sort(c.training_boot_ids(:))));
    assert(candidate.critic_initialization_report.ridge_initialization_fits==2);
end
report=struct(passed=true,global_rng_unchanged_by_ridge=true,permutation_error=permutationError, ...
    twin_models_distinct=true,nonzero_Ki_rejected=rejected,single_boot_rejected=oneBootRejected, ...
    historical_mode_matches_preserved_trainer_error=legacyError, ...
    warm_training_uses_training_boots_only=true,corrected_lambda_default_verified=true, ...
    test_only_double_critic_update_iterations=legacy.critic_update_iterations+current.critic_update_iterations+warm.critic_update_iterations, ...
    test_only_actor_updates=legacy.actor_updates+current.actor_updates+warm.actor_updates, ...
    initializer=fit,hardware_accessed=false,actor_applied=false,candidate_admission=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(fullfile(output,'regression-summary.json'),'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(rmfield(report,'initializer')));
end
function x=matrix(rows,name)
parts=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);x=single(cat(2,parts{:}));
end
function d=distance(a,b)
d=0;for k=1:height(a.Learnables),d=max(d,max(abs(double(extractdata(a.Learnables.Value{k}-b.Learnables.Value{k}))),[],'all'));end
end
