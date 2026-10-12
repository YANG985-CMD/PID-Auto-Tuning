"""Offline protocol, stale-response and worker-stall checks; no hardware access."""
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch
from speedloop_shadow import (ShadowClient, validate_reply, f32, SCALES, CHECKPOINT_SHA, POLICY)


def sample():
    return dict(seq=10,t_us=500000,boot_id='0123456789abcdef',fault=0,enabled=True,
                speed_ref=1000.,speed=1010.,error_history=-10.,integral_output=.01,
                current=.5,vbus=24.,kp=f32(.003389),ki=f32(.00144),elapsed_ms=2300.)


def reply(request):
    t=request['telemetry']
    raw=[t['speed_ref'],t['speed'],t['speed_ref']-t['speed'],t['error_history'],
         t['integral_output'],t['current'],t['vbus'],t['kp'],t['ki'],t['elapsed_ms']]
    action=[.2,-.4]
    gains=[f32(t['kp']+.00027112*action[0]),f32(t['ki']+.000144*action[1])]
    return dict(ok=True,request_id=request['request_id'],result=dict(
        policy_version=POLICY,checkpoint_sha256=CHECKPOINT_SHA,shadow_only=True,
        hardware_writeback=False,training_performed=False,telemetry_seq=t['seq'],
        t_us=t['t_us'],boot_id=t['boot_id'],ki_masked=True,deployment_allowed=False,
        raw_state=raw,observation=[f32(max(-5,min(5,x/s))) for x,s in zip(raw,SCALES)],
        raw_action=action,original_two_head_gains=gains,kp=gains[0],ki=f32(.00144),inference_ms=2.))


class ShadowChecks(unittest.TestCase):
    def setUp(self):
        self.request=dict(op='predict',request_id=2,telemetry=sample())
        self.response=reply(self.request)

    def test_independent_mapping_and_ki_mask(self):
        result=validate_reply(self.response,self.request)
        self.assertEqual(result['ki'],f32(.00144))
        self.assertNotEqual(result['ki'],result['original_two_head_gains'][1])

    def test_cross_session_or_old_packet_rejected(self):
        for key,value in [('telemetry_seq',9),('t_us',499999),('boot_id','ffffffffffffffff')]:
            corrupted=json.loads(json.dumps(self.response)); corrupted['result'][key]=value
            with self.assertRaises(ValueError): validate_reply(corrupted,self.request)

    def test_writeback_and_unreviewed_checkpoint_rejected(self):
        for key,value in [('hardware_writeback',True),('checkpoint_sha256','0'*64),('ki_masked',False)]:
            corrupted=json.loads(json.dumps(self.response)); corrupted['result'][key]=value
            with self.assertRaises(ValueError): validate_reply(corrupted,self.request)

    def test_invalid_or_modified_action_and_scale_rejected(self):
        for key,value in [('raw_action',[float('nan'),0]),('kp',.01),('observation',[0]*10)]:
            corrupted=json.loads(json.dumps(self.response)); corrupted['result'][key]=value
            with self.assertRaises(ValueError): validate_reply(corrupted,self.request)

    def fake_server(self, delay, with_predict=False):
        listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(1)
        port=listener.getsockname()[1]
        def serve():
            try:
                with listener,listener.accept()[0] as conn:
                    stream=conn.makefile('rb')
                    req=json.loads(stream.readline())
                    hello=dict(ok=True,request_id=req['request_id'],result=dict(
                        policy_version=POLICY,checkpoint_sha256=CHECKPOINT_SHA,shadow_only=True,
                        hardware_writeback=False,training_performed=False,state_scale=SCALES))
                    conn.sendall(json.dumps(hello).encode()+b'\n')
                    line=stream.readline()
                    if not line: return
                    req=json.loads(line); time.sleep(delay)
                    if with_predict: conn.sendall(json.dumps(reply(req)).encode()+b'\n')
            except (ConnectionError,OSError): pass
        thread=threading.Thread(target=serve,daemon=True); thread.start()
        with patch('speedloop_shadow.Path.read_text',return_value='a'*64):
            client=ShadowClient(port,'unused-token')
        self.assertTrue(client.ready.wait(1))
        return client,thread

    def test_network_stall_never_blocks_submission_or_stop_thread(self):
        client,server=self.fake_server(.3)
        client.submit(sample())
        time.sleep(.02)
        started=time.perf_counter()
        for i in range(100): client.submit(dict(sample(),seq=20+i,t_us=600000+i))
        self.assertLess(time.perf_counter()-started,.02)
        self.assertLessEqual(client.pending.qsize(),1)
        self.assertTrue(client.close()); server.join(1)
        self.assertIn('timed out',client.error)

    def test_late_prediction_is_logged_but_rejected(self):
        client,server=self.fake_server(.07,True)
        client.submit(sample()); time.sleep(.1)
        records=client.drain(); self.assertTrue(client.close()); server.join(1)
        delayed=[r for r in records if 'result' in r]
        self.assertEqual(len(delayed),1)
        self.assertFalse(delayed[0]['accepted'])
        self.assertEqual(delayed[0]['rejection'],'source_deadline_exceeded')

    def test_stale_source_is_rejected_without_prediction(self):
        client,server=self.fake_server(.1)
        client.submit(sample(),time.perf_counter()-.1); time.sleep(.03)
        records=client.drain(); self.assertTrue(client.close()); server.join(1)
        self.assertEqual(records[0]['rejection'],'source_stale_before_inference')
        self.assertNotIn('result',records[0])


if __name__=='__main__': unittest.main()
