function report=auditMotorCriticStateInputs(study,output)
% Recorded TRAIN states only. Input perturbations are not plant counterfactuals.
arguments
    study (1,1) string
    output (1,1) string
end
assert(~isfile(output));summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
items=summary.input_manifest(string({summary.input_manifest.split})=="train");results=struct([]);
for candidate=summary.candidates(:)'
    file=fullfile(study,"candidate-"+string(candidate.reward_profile)+"-seed-"+candidate.seed+".mat");
    s=load(file,'experimentalAgent','contract');vectors=cell(numel(items),1);
    for index=1:numel(items)
        assert(motorFileSHA256(items(index).file)==string(items(index).sha256));
        [e,~]=motorLiveWindowExperience(jsondecode(fileread(items(index).file)),s.contract);
        vectors{index}=e.Observation{1};
    end
    obs=single(cat(2,vectors{:}));other=obs;other(10,:)=-other(10,:);
    previous=obs;previous(8,:)=-previous(8,:);
    critics=getCritic(s.experimentalAgent);actions=[-.9875 -.5 0];values=zeros(2,3,size(obs,2));
    clocks=zeros(2,size(obs,2));kpEffects=clocks;
    for index=1:2
        for level=1:3
            a=single([repmat(actions(level),1,size(obs,2));zeros(1,size(obs,2))]);
            values(index,level,:)=reshape(double(getValue(critics(index),{obs},{a})),1,1,[]);
            if level==2
                base=reshape(values(index,level,:),1,[]);
                clocks(index,:)=abs(base-reshape(double(getValue(critics(index),{other},{a})),1,[]));
                kpEffects(index,:)=abs(base-reshape(double(getValue(critics(index),{previous},{a})),1,[]));
            end
        end
    end
    span=reshape(max(values,[],2)-min(values,[],2),2,[]);
    row=struct(seed=candidate.seed,reward_profile=string(candidate.reward_profile),training_states=size(obs,2), ...
        mean_action_grid_q_span=mean(span,2)',mean_clock_perturbation_effect=mean(clocks,2)', ...
        mean_actual_kp_perturbation_effect=mean(kpEffects,2)',clock_clipped_fraction=mean(abs(obs(10,:))>=4.999), ...
        clock_effect_over_action_span=mean(clocks,2)'./max(mean(span,2)',eps), ...
        checkpoint_sha256=motorFileSHA256(file));
    if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
end
report=struct(source="recorded-training-state-critic-input-audit",training_states_only=true, ...
    results=results,hardware_accessed=false,input_perturbations_are_physical_counterfactuals=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
for r=results,disp(jsonencode(struct(seed=r.seed,profile=r.reward_profile,clock_effect_over_action_span=r.clock_effect_over_action_span)));end
end
