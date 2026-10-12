function hash = motorFileSHA256(filename)
% SHA-256 of exact checkpoint bytes; never print file contents.
fid=fopen(filename,'rb'); assert(fid>=0);
closer=onCleanup(@()fclose(fid));
digest=java.security.MessageDigest.getInstance('SHA-256');
digest.update(fread(fid,Inf,'*uint8'));
hash=string(lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2)',1,[])));
end
