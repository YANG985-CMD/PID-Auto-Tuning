"""Reject authentication/replay/domain errors using the actual MATLAB server, no hardware."""
import argparse
import json
from pathlib import Path
import socket
from speedloop_shadow import validate_reply, FIRMWARE


def verify(port, token_file, telemetry_file, output):
    output=Path(output).resolve()
    if Path('E:/simulink/_codex_tmp').resolve() not in output.parents: raise ValueError('Temporary root required')
    output.mkdir(parents=True,exist_ok=True)
    token=Path(token_file).read_text(encoding='ascii').strip()
    telemetry=json.loads(Path(telemetry_file).read_text(encoding='utf-8').splitlines()[0])
    checks={}
    with socket.create_connection(('127.0.0.1',port),timeout=1) as sock:
        sock.settimeout(1); stream=sock.makefile('rb')
        def call(number,op,**fields):
            request=dict(schema_version=1,request_id=number,op=op,token=token,
                         shadow_only=True,hardware_writeback=False,**fields)
            sock.sendall(json.dumps(request).encode()+b'\n')
            response=json.loads(stream.readline())
            assert response['request_id']==number
            return request,response
        req,res=call(1,'hello'); validate_reply(res,req); checks['actual_matlab_handshake']=True
        req,res=call(2,'predict',firmware_id=FIRMWARE,telemetry=telemetry)
        validate_reply(res,req); checks['actual_matlab_prediction_mapping']=True
        _,res=call(3,'predict',firmware_id=FIRMWARE,telemetry=telemetry)
        assert not res['ok']; checks['duplicate_source_rejected']=True
        changed=dict(telemetry,boot_id='ffffffffffffffff',seq=telemetry['seq']+1,t_us=telemetry['t_us']+20000)
        _,res=call(4,'predict',firmware_id=FIRMWARE,telemetry=changed)
        assert not res['ok']; checks['cross_boot_source_rejected']=True
        token='0'*64
        _,res=call(5,'hello'); assert not res['ok']; checks['wrong_token_rejected']=True
    report=dict(passed=True,hardware_accessed=False,td3_training_performed=False,
                hardware_writeback=False,actual_matlab_server_used=True,checks=checks)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report)); return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    for key in ('token-file','telemetry','output'): parser.add_argument('--'+key,required=True)
    a=parser.parse_args(); verify(a.port,a.token_file,a.telemetry,a.output)
