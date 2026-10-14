function trace = ccmp_trace(out)
t=out.yout{2}.Values.Time; speed=double(out.yout{2}.Values.Data);
reference=double(resample(out.yout{1}.Values,t,'zoh').Data);
current=double(resample(out.yout{3}.Values,t,'zoh').Data);
iq=double(resample(out.yout{4}.Values,t,'zoh').Data);
gains=double(resample(out.yout{5}.Values,t,'zoh').Data);
load=double(resample(out.yout{6}.Values,t,'zoh').Data);
current=reshape(current,numel(t),3); gains=reshape(gains,numel(t),2);
trace=table(t,reference,speed,current(:,1),current(:,2),current(:,3),iq,gains(:,1),gains(:,2),load, ...
    'VariableNames',{'time_s','reference_rpm','speed_rpm','ia_A','ib_A','ic_A','iq_ref_A','Kp','Ki','load_Nm'});
assert(all(isfinite(trace{:,:}),'all'),'Comparison:Nonfinite','Simulation returned nonfinite data');
end
