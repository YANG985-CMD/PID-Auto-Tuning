function report=runSpeedLoopOfflineStudy(repository,outputDir)
% A fixed episode split and matched seeds for a real-data-only ablation.
arguments
    repository (1,1) string
    outputDir (1,1) string
end
base=fullfile(repository,'examples','speedloop-v5-real-20261012');
runs=string(base);
for k=1:16
    runs(end+1,1)=fullfile(base,'trials',sprintf('trial-%02d',k)); %#ok<AGROW>
end
batches=["repeated-ab-20261012","ki-coverage-20261012","ki-coverage-2-20261012"];
for batch=batches
    folders=dir(fullfile(base,batch,'round-*'));
    folders=folders([folders.isdir]);
    [~,order]=sort({folders.name}); folders=folders(order);
    assert(numel(folders)==6);
    for k=1:6
        runs(end+1,1)=fullfile(base,batch,folders(k).name); %#ok<AGROW>
    end
end
assert(numel(runs)==35);
holdout=[5;10;15;20;23;25;29;31;35];
names=["legacy-td3","enhanced-td3","legacy-td3-bc","enhanced-td3-bc"];
profiles=["legacy-v1","current-speed-penalty-v2","legacy-v1","current-speed-penalty-v2"];
bcWeights=[0,0,2.5,2.5];
reports=cell(1,4);
for k=1:4
    fprintf('Offline ablation %d/4: %s\n',k,names(k));
    reports{k}=trainSpeedLoopReweightedTD3(runs,fullfile(outputDir,names(k)),true, ...
        [7;17;27],[1 1],RewardProfile=profiles(k), ...
        BehaviorCloningWeight=bcWeights(k),ValidationRunIndices=holdout);
end
report=struct(schema_version=1,hardware_accessed=false,source="real_motor", ...
    study="reward-and-behavior-cloning-ablation",configs=names, ...
    reports={reports},validation_run_indices=holdout', ...
    total_gradient_steps=sum(cellfun(@(r)sum([r.seed_reports.training_steps_total]),reports)), ...
    physical_performance_verified=false,deployment_allowed=false,performance_claim_allowed=false);
fid=fopen(fullfile(outputDir,'study-summary.json'),'wb'); assert(fid>=0);
closer=onCleanup(@()fclose(fid)); %#ok<NASGU>
fwrite(fid,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'),'uint8');
end
