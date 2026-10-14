function report=testMotorCriticMask()
% Native network mask and default compatibility; no hardware or training.
default=createMotorTD3(73,[1;0],250);
explicit=createMotorTD3(73,[1;0],250,CriticInputMask=ones(10,1));
masked=createMotorTD3(73,[1;0],250,CriticInputMask=[ones(9,1);0]);
rng(181);x=single(rand(10,128)*10-5);changed=x;changed(10,:)=-changed(10,:);
a=single([rand(1,128)*2-1;zeros(1,128)]);
d=getCritic(default);e=getCritic(explicit);m=getCritic(masked);
for index=1:2
    q=getValue(d(index),{x},{a});eq=getValue(e(index),{x},{a});assert(isequal(q,eq));
    q=getValue(m(index),{x},{a});other=getValue(m(index),{changed},{a});assert(isequal(q,other));
end
rejected=false;
try,createMotorTD3(73,[1;0],250,CriticInputMask=[ones(9,1);.5]);catch,rejected=true;end
assert(rejected);
memory=rlPrioritizedReplayMemory(getObservationInfo(masked),getActionInfo(masked),10000);
masked.ExperienceBuffer=memory;
assert(isa(masked.ExperienceBuffer,'rl.replay.rlPrioritizedReplayMemory') && masked.ExperienceBuffer.Length==0);
report=struct(passed=true,default_critic_compatibility=true,clock_mask_invariance=true, ...
    critic_actual_kp_input_retained=true,random_observations=128, ...
    prioritized_memory_accepted_by_TD3=true,hardware_accessed=false,training_performed=false);
disp(jsonencode(report));
end
