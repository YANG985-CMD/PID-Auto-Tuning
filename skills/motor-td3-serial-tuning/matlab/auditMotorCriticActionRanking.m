function report=auditMotorCriticActionRanking(studies,output)
% Recorded holdout states: Q ranking is a model diagnostic, not motor response.
arguments
    studies (:,1) string
    output (1,1) string
end
assert(~isfile(output));results=struct([]);
actions=[(double(single(.003121269))-double(single(.003389)))/.00027112 -.5 0];
for study=studies'
    summary=jsondecode(fileread(fullfile(study,'training-summary.json')));
    items=summary.input_manifest(string({summary.input_manifest.split})=="validation");
    for candidate=summary.candidates(:)'
        file=fullfile(study,"candidate-"+string(candidate.reward_profile)+"-seed-"+candidate.seed+".mat");
        s=load(file,'experimentalAgent','contract');vectors=cell(numel(items),1);
        for index=1:numel(items)
            assert(motorFileSHA256(items(index).file)==string(items(index).sha256));
            [e,~]=motorLiveWindowExperience(jsondecode(fileread(items(index).file)),s.contract);
            vectors{index}=e.Observation{1};
        end
        obs=single(cat(2,vectors{:}));critics=getCritic(s.experimentalAgent);
        q=zeros(2,3,size(obs,2));
        for index=1:2
            for level=1:3
                a=single([repmat(actions(level),1,size(obs,2));zeros(1,size(obs,2))]);
                q(index,level,:)=reshape(double(getValue(critics(index),{obs},{a})),1,1,[]);
            end
        end
        [~,rank1]=max(reshape(q(1,:,:),3,[]),[],1);
        [~,rank2]=max(reshape(q(2,:,:),3,[]),[],1);
        [best,choice]=max(reshape(min(q,[],1),3,[]),[],1);
        actor=getActor(s.experimentalAgent);a=getAction(actor,{obs});
        policyQ=min(reshape(double(getValue(critics(1),{obs},{a{1}})),1,[]), ...
            reshape(double(getValue(critics(2),{obs},{a{1}})),1,[]));
        row=struct(study=study,seed=candidate.seed,profile=string(candidate.reward_profile), ...
            validation_states=size(obs,2),tested_actions=actions, ...
            min_twin_critic_best_level_counts=[sum(choice==1) sum(choice==2) sum(choice==3)], ...
            twin_critic_ranking_agreement_fraction=mean(rank1==rank2), ...
            mean_best_grid_Q_minus_Actor_Q=mean(best-policyQ), ...
            mean_Q_by_grid_level=squeeze(mean(q,3)),checkpoint_sha256=motorFileSHA256(file));
        if isempty(results),results=row;else,results(end+1)=row;end %#ok<AGROW>
    end
end
report=struct(source="frozen-critic-action-grid-diagnostic",results=results, ...
    Q_values_are_physical_performance=false,hardware_accessed=false,weights_changed=false, ...
    deployment_allowed=false,performance_claim_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
for r=results,disp(jsonencode(struct(study=r.study,seed=r.seed,best_counts=r.min_twin_critic_best_level_counts,twin_agreement=r.twin_critic_ranking_agreement_fraction)));end
end
