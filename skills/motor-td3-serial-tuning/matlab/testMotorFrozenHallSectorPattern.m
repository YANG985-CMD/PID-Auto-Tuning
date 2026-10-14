function report=testMotorFrozenHallSectorPattern(output)
% Known sector patterns with unequal per-boot sample counts.
assert(~isfile(output));pattern=[-3;-2;-1;1;2;3];parts=cell(2,1);
for b=1:2
    repeats=2*10^(b-1);codes=repmat((1:6)',repeats,1);n=numel(codes);
    errors=(30-25*b)+b*pattern(codes);
    parts{b}=table(repmat("boot"+b,n,1),repmat("train",n,1), ...
        repmat(10000,n,1),repmat(.003389,n,1),repmat(.003389,n,1), ...
        codes,repmat(100,n,1),errors, ...
        VariableNames=["Boot","Split","Elapsed_ms","SourceKp","TargetKp","HallCode","Width_us","Error_rpm"]);
end
T=vertcat(parts{:});model=fitMotorFrozenHallSectorPattern(T);
err=max(abs(model.deviation_rpm-1.5*pattern));assert(err<1e-12);
assert(model.equal_boot_mass && numel(model.fitting_boots)==2);
rejected=0;
for k=1:4
    bad=T;
    if k==1,bad.Split(1)="validation";elseif k==2,bad.Elapsed_ms(1)=9999;
    elseif k==3,bad.TargetKp(1)=.0035;else,bad.HallCode(1)=0;end
    try
        fitMotorFrozenHallSectorPattern(bad);
    catch e
        assert(string(e.identifier)=="MATLAB:assertion:failed");rejected=rejected+1;
    end
end
assert(rejected==4);
report=struct(passed=true,known_pattern_maximum_error=err,unequal_boot_sample_mass_does_not_change_fit=true, ...
    rejected_invalid_training_cases=rejected,hardware_accessed=false,TD3_gradient_updates=0,deployment_allowed=false);
f=fopen(output,'wb');assert(f>=0);fwrite(f,unicode2native(jsonencode(report,PrettyPrint=true),'UTF-8'));fclose(f);
disp(jsonencode(report));
end
