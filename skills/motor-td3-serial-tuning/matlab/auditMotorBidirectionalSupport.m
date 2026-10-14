function report=auditMotorBidirectionalSupport(rows,output)
% Count measured status coverage; no synthetic rows and no gradient updates.
gains=unique(cellfun(@(r)r.actual_target_kp,rows));groups=struct([]);
for gain=gains(:)'
    g=struct(target_kp=gain);
    for mode=[false true]
        selected=rows(cellfun(@(r)r.actual_target_kp==gain && (r.actual_source_kp~=r.actual_target_kp)==mode,rows));
        count=numel(selected);boots=numel(unique(string(cellfun(@(r)r.boot_id,selected,UniformOutput=false))));
        if mode,g.switch_rows=count;g.switch_boots=boots;else,g.hold_rows=count;g.hold_boots=boots;end
    end
    g.qualified=g.hold_rows>=4 && g.switch_rows>=4 && g.hold_boots>=2 && g.switch_boots>=2;
    if isempty(groups),groups=g;else,groups(end+1)=g;end %#ok<AGROW>
end
report=struct(groups=groups,all_target_status_groups_qualified=all([groups.qualified]), ...
    minimum_rows=4,minimum_training_boots=2,gate_relaxed=false,new_physical_evidence_created=false, ...
    gradient_updates=0,deployment_allowed=false,performance_claim_allowed=false);
assert(~isfile(output));f=fopen(output,'wb');fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);disp(jsonencode(report));
end
