function openComparison()
root=fileparts(mfilename('fullpath')); addpath(root); ccmp_init();
open_system(fullfile(root,'MotorTunerComparison.slx'));
end
