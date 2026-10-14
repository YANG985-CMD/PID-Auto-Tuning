function digest=ccmp_sha256(path)
file=fopen(path,'rb');assert(file>=0);cleanup=onCleanup(@()fclose(file));
md=java.security.MessageDigest.getInstance('SHA-256');
while true
    bytes=fread(file,65536,'*uint8');if isempty(bytes),break;end
    md.update(typecast(bytes,'int8'));
end
digest=lower(reshape(dec2hex(typecast(md.digest(),'uint8'),2)',1,[]));
end
