function c = ccmp_config()
% Simulation parameters. Nominal guard bounds are not hardware validation.
c.baseline = [.003389; .00144];
c.lower = [.0013556; .00072];
c.upper = [.0054224; .00216];
c.step = [.00027112; .000144];
c.focTs = 1e-4;
c.speedTs = 1e-3;
c.telemetryTs = .02;
c.tunerTs = .1;
c.stopTime = 6;
c.tmp = 'E:/simulink/_codex_tmp/simulink-four-tuners-20261013';
c.reference = 'E:/dianji/Folder 2 Program Model/17.SpeedLoop/5.SpeedLoop/SpeedLoop_Model';
c.labels = ["AI skill approved plan replay", "Fuzzy PI", ...
    "Neural PI rule supervised", "TD3 frozen experimental Actor", "Fixed baseline PI"];
end
