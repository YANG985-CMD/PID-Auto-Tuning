function report=auditMotorConditionalActionSupport(input,output)
% Actual transition coverage and nearby states; no counterfactual performance.
arguments
    input (1,1) string
    output (1,1) string
end
assert(~isfile(output));s=load(input);assert(s.fullHallAudit.passed);
training=s.fullHallTrain;validation=s.fullHallValidation;rows=[training;validation];
source=cellfun(@(r)r.actual_source_kp,rows);target=cellfun(@(r)r.actual_target_kp,rows);
gainLevels=unique([source;target]);actionLevels=unique(cellfun(@(r)r.action_normalized(1),training));
n=numel(gainLevels);assert(n>=3 && numel(actionLevels)==n);
counts=zeros(n,n,2);bootCounts=counts;splits={training,validation};
for split=1:2
    for r=splits{split}'
        counts(gainLevels==r{1}.actual_source_kp,gainLevels==r{1}.actual_target_kp,split)= ...
            counts(gainLevels==r{1}.actual_source_kp,gainLevels==r{1}.actual_target_kp,split)+1;
    end
    for sourceIndex=1:n
        for targetIndex=1:n
            mask=cellfun(@(r)r.actual_source_kp==gainLevels(sourceIndex) && r.actual_target_kp==gainLevels(targetIndex),splits{split});
            boots=cellfun(@(r)r.boot_id,splits{split}(mask),UniformOutput=false);
            bootCounts(sourceIndex,targetIndex,split)=numel(unique(string(boots)));
        end
    end
end
x=matrix(training,'observation');a=matrix(training,'action_normalized');vx=matrix(validation,'observation');
mask=s.fullHallContract.critic_input_mask(:);
features=double(motorLocalQuadraticFeatures(single(x.*mask),single(a)));
center=mean(features,2);scale=max(std(features,0,2),1e-3);
design=[((features-center)./scale)' ones(numel(training),1)];
singular=svd(design,'econ');condition=singular(1)/max(singular(end),eps);
active=logical(mask);active(8)=false;
trainSource=cellfun(@(r)r.actual_source_kp,training);trainTarget=cellfun(@(r)r.actual_target_kp,training);
trainReference=cellfun(@(r)r.actual_reference_rpm,training);
nearest=nan(numel(validation),n);withinHalf=zeros(numel(validation),n);withinOne=withinHalf;
available=withinHalf;
reachable=false(numel(validation),n);
for k=1:numel(validation)
    r=validation{k};sameStateCategory=trainSource==r.actual_source_kp & trainReference==r.actual_reference_rpm;
    for action=1:n
        reachable(k,action)=abs(r.actual_source_kp-gainLevels(action))<=.00013556+1e-9;
        ids=find(sameStateCategory & trainTarget==gainLevels(action));available(k,action)=numel(ids);
        if isempty(ids),continue;end
        distance=sqrt(mean((x(active,ids)-vx(active,k)).^2,1));
        nearest(k,action)=min(distance);withinHalf(k,action)=sum(distance<=.5);withinOne(k,action)=sum(distance<=1);
    end
end
support=struct([]);
for action=1:n
    distance=sort(nearest(isfinite(nearest(:,action)),action));
    q=nan(1,3);if ~isempty(distance),q=distance(max(1,ceil([.25 .5 .9]*numel(distance))));end
    r=struct(target_kp=gainLevels(action),validation_queries=numel(validation), ...
        no_same_source_gain_and_reference_training_action=sum(available(:,action)==0), ...
        nearby_training_count_ge5_radius0p5_fraction=mean(withinHalf(:,action)>=5), ...
        nearby_training_count_ge5_radius1_fraction=mean(withinOne(:,action)>=5), ...
        finite_nearest_RMS_standardized_distance_quartile_median_p90=q);
    if isempty(support),support=r;else,support(end+1)=r;end %#ok<AGROW>
end
status=struct([]);splitNames=["train","validation"];balancedFraction=zeros(1,2);
for split=1:2
    splitRows=splits{split};targetValues=cellfun(@(r)r.actual_target_kp,splitRows);
    switched=cellfun(@(r)r.actual_source_kp~=r.actual_target_kp,splitRows);
    proportions=zeros(1,n);
    for k=1:n
        at=targetValues==gainLevels(k);change=at & switched;hold=at & ~switched;
        proportions(k)=sum(change)/sum(at);
        value=struct(split=splitNames(split),target_kp=gainLevels(k), ...
            hold_windows=sum(hold),switch_windows=sum(change), ...
            switch_boots=numel(unique(string(cellfun(@(r)r.boot_id,splitRows(change),UniformOutput=false)))), ...
            switch_fraction_within_action=proportions(k));
        if isempty(status),status=value;else,status(end+1)=value;end %#ok<AGROW>
    end
    balancedFraction(split)=mean(proportions);
end
report=struct(passed=true,input_sha256=motorFileSHA256(input), ...
    training_windows=numel(training),validation_windows=numel(validation), ...
    source_gain_levels=gainLevels,target_gain_levels=gainLevels, ...
    train_source_gain_by_target_counts=counts(:,:,1),validation_source_gain_by_target_counts=counts(:,:,2), ...
    train_source_gain_by_target_boot_counts=bootCounts(:,:,1),validation_source_gain_by_target_boot_counts=bootCounts(:,:,2), ...
    action_status_counts=status,expected_switch_fraction_under_balanced_actions=balancedFraction, ...
    missing_train_transition_count=sum(counts(:,:,1)==0,'all'),missing_validation_transition_count=sum(counts(:,:,2)==0,'all'), ...
    local_quadratic_design_columns=size(design,2),numerical_rank_relative1e6=sum(singular>singular(1)*1e-6), ...
    numerical_rank_relative1e10=sum(singular>singular(1)*1e-10),design_condition_number=condition, ...
    singular_values=singular,conditional_neighborhood_support=support, ...
    action_count=n,all_actions_have_same_category_training_support_fraction=mean(all(available>0,2)), ...
    all_actions_have_ge5_nearby_radius1_fraction=mean(all(withinOne>=5,2)), ...
    reachable_actions_category_support_fraction=mean(all(available>0 | ~reachable,2)), ...
    reachable_actions_ge5_nearby_radius1_fraction=mean(all(withinOne>=5 | ~reachable,2)), ...
    physical_reachable_action_step=.00013556, ...
    neighborhood_radii_are_descriptive_not_performance_gates=true, ...
    feature_redundancy_is_not_policy_identifiability_proof=true, ...
    actual_actions_only=true,hardware_accessed=false,training_performed=false, ...
    candidate_admission=false,deployment_allowed=false,performance_claim_allowed=false);
if n==3
    report.all_three_actions_have_same_category_training_support_fraction=mean(all(available>0,2));
    report.all_three_actions_have_ge5_nearby_radius1_fraction=mean(all(withinOne>=5,2));
end
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(rmfield(report,'singular_values')));
end
function values=matrix(rows,name)
parts=cellfun(@(r)r.(name)(:),rows,UniformOutput=false);values=double(cat(2,parts{:}));
end
