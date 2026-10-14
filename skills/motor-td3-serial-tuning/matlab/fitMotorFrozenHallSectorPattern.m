function model=fitMotorFrozenHallSectorPattern(T)
% Fit boot-centered Hall-code associations using baseline training data only.
assert(all(T.Split=="train") && all(T.Elapsed_ms>=10000));
assert(all(abs(T.SourceKp/.003389-1)<1e-6) && all(T.SourceKp==T.TargetKp));
assert(all(T.Width_us>0) && all(isfinite(T.Error_rpm)));
T.WeightedError=T.Width_us.*T.Error_rpm;
G=groupsummary(T,["Boot","HallCode"],"sum",["Width_us","WeightedError"]);
B=groupsummary(T,"Boot","sum",["Width_us","WeightedError"]);
assert(height(G)==height(B)*6 && all(ismember(G.HallCode,1:6)));
[matched,where]=ismember(G.Boot,B.Boot);assert(all(matched));
G.BootMeanError=B.sum_WeightedError(where)./B.sum_Width_us(where);
G.CenteredMeanError=G.sum_WeightedError./G.sum_Width_us-G.BootMeanError;
G.SectorExposureFraction=G.sum_Width_us./B.sum_Width_us(where);
P=groupsummary(G,"HallCode","mean",["CenteredMeanError","SectorExposureFraction"]);
assert(isequal(P.HallCode(:),(1:6)'));
offset=sum(P.mean_CenteredMeanError.*P.mean_SectorExposureFraction);
P.FrozenDeviation=P.mean_CenteredMeanError-offset;
model=struct(codes=P.HallCode,deviation_rpm=P.FrozenDeviation, ...
    fitting_boots=B.Boot,training_only=true,equal_boot_mass=true, ...
    training_boot_sector_statistics=table2struct(G), ...
    sector_exposure_fraction=P.mean_SectorExposureFraction, ...
    weighted_training_pattern_mean=sum(P.FrozenDeviation.*P.mean_SectorExposureFraction), ...
    independent_speed_ground_truth=false,feedback_or_primary_metric_changed=false);
assert(abs(model.weighted_training_pattern_mean)<1e-10);
end
