function report = evaluateCheckpoint(port,tokenFile,checkpointFile,outputFile)
% Live bridge must explicitly select this candidate with --approved-policy.
data = load(checkpointFile,'agent','profile','report');
client = MotorTD3Client(port,tokenFile);
assert(strcmp(client.Profile.profile_id,data.profile.profile_id), 'Profile identity mismatch');
assert(strcmp(client.Profile.training.normalization_id,data.profile.training.normalization_id), 'Normalization identity mismatch');
assert(strcmp(client.Profile.training.action_mapping_id,data.profile.training.action_mapping_id), 'Action mapping mismatch');
assert(isequal(client.Profile.controller,data.profile.controller), 'Gain contract mismatch');
assert(isequal(client.Profile.runtime,data.profile.runtime), 'Runtime contract mismatch');
if ~client.SimulationOnly
    assert(~data.report.simulation_only, 'Mock policy cannot be used on a real motor');
end
cleanup = onCleanup(@() stopSafely(client));
report = evaluateMotorTD3(client,data.agent,data.report.policy_version);
fid = fopen(outputFile,'w'); assert(fid >= 0);
closer = onCleanup(@() fclose(fid));
fprintf(fid,'%s\n',jsonencode(report,'PrettyPrint',true));
end

function stopSafely(client)
try
    client.stop();
catch exception
    warning('MotorTD3:StopUnconfirmed','%s',exception.message);
end
end
