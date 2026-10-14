function [learning,contract]=prepareMotorCausalReplay(replay,coordinates,standardize,options)
% Change learner coordinates, never relabel the physical gain-change record.
arguments
    replay (1,1) struct
    coordinates (1,1) string {mustBeMember(coordinates,["delta","absolute-target"])}
    standardize (1,1) logical
    options.ObservationProfile (1,1) string {mustBeMember(options.ObservationProfile,["physical","history20-40"])} = "physical"
    options.LearningTask (1,1) string {mustBeMember(options.LearningTask,["continuing","bounded-trial"])} = "continuing"
end
raw=single(cell2mat(cellfun(@(r)sourceObservation(r,options),replay.train,UniformOutput=false)'));
center=zeros(10,1);scale=ones(10,1);
if standardize
    center=double(mean(raw,2));scale=max(.01,double(std(raw,0,2)));
end
contract=struct(action_coordinates=coordinates,state_standardized=standardize, ...
    observation_profile=options.ObservationProfile,learning_task=options.LearningTask, ...
    state_center=center',state_scale=scale',state_standard_deviation_floor=.01, ...
    engineering_state_scale=[1000,1000,1000,1000,3,2,24,.003389,.00144,3000], ...
    encoded_baseline_gains=double(single([.003389,.00144])), ...
    gain_step_scale=[.00027112,.000144],observation_clip=5, ...
    normalizer_fit_split="training-source-states-only",runtime_compatible=false, ...
    reward_action_cost_basis="Original physical delta; held nonzero targets do not get a new change penalty", ...
    additional_physical_trials=0,additional_replay_rows=0,hardware_accessed=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
contract.raw_engineering_state_scale=contract.engineering_state_scale;
contract.feature_names=["speed_ref","speed","speed_error","error_history_1ms","integral_output", ...
    "nominal_current","vbus","actual_kp","actual_ki","elapsed_ms"];
if options.ObservationProfile=="history20-40"
    assert(isfield(replay.summary,'history_depth_packets') && replay.summary.history_depth_packets==2);
    contract.feature_names([4 9])=["error_previous_telemetry_20ms","error_two_telemetry_packets_40ms"];
    contract.engineering_state_scale(9)=1000;
end
if options.LearningTask=="bounded-trial"
    assert(isfield(replay.summary,'bounded_done_rows') && replay.summary.bounded_done_rows>0);
    contract.feature_names(10)="remaining_bounded_trial_ms";
    contract.bounded_horizon_ms=8000;
    contract.physical_termination_flags_preserved=true;
    contract.learning_terminal_basis="Real successful STOP and shutdown end the explicitly bounded experiment task";
end
learning=replay;
for name=["train","validation"]
    rs=replay.(name);
    for k=1:numel(rs)
        r=rs{k};r.physical_delta_action=r.action_normalized;
        r.original_engineering_observation=r.observation;
        r.original_engineering_next_observation=r.next_observation;
        r.observation=max(-5,min(5,(sourceObservation(r,options)-center)./scale));
        r.next_observation=max(-5,min(5,(nextObservation(r,options)-center)./scale));
        r.learning_is_done=options.LearningTask=="bounded-trial" && isfield(r,'learning_is_done') && r.learning_is_done;
        if options.LearningTask=="bounded-trial"
            r.physical_reward=r.reward;r.reward=r.learning_reward;
        end
        if coordinates=="absolute-target"
            r.action_normalized=(r.action_applied(:)-contract.encoded_baseline_gains(:))./contract.gain_step_scale(:);
            reconstructed=contract.encoded_baseline_gains(:)+r.action_normalized.*contract.gain_step_scale(:);
        else
            reconstructed=r.state(8:9)+r.action_normalized(:).*contract.gain_step_scale(:);
        end
        assert(all(abs(reconstructed-r.action_applied(:))<1e-12));
        assert(all(isfinite([r.observation(:);r.next_observation(:);r.action_normalized(:)])));
        assert(all(abs(r.action_normalized)<=1+1e-6));
        rs{k}=r;
    end
    learning.(name)=rs;
end
end

function x=sourceObservation(r,options)
if options.ObservationProfile=="history20-40",x=r.history_observation(:);else,x=r.observation(:);end
if options.LearningTask=="bounded-trial",x(10)=max(0,8000-r.state(10))/3000;end
end

function x=nextObservation(r,options)
if options.LearningTask=="bounded-trial"
    if options.ObservationProfile=="history20-40",x=r.learning_history_next_observation(:);
    else,x=r.learning_next_observation(:);end
    % Terminal next value is masked. Keep actual recorded final observation;
    % zero remaining objective time is a task feature, not a motor measurement.
    if r.learning_is_done,x(10)=0;else,x(10)=max(0,8000-r.next_state(10))/3000;end
else
    if options.ObservationProfile=="history20-40",x=r.history_next_observation(:);else,x=r.next_observation(:);end
end
end
