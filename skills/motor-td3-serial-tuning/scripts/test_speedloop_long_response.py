import unittest
from speedloop_stream_training import CausalStream,GAINS
from test_speedloop_stream_training import packet,proof

class Checks(unittest.TestCase):
    def test_duration_guard_and_default(self):
        self.assertEqual(CausalStream().minimum_response_span_us,60000)
        for value in (True,200000.,0,60001,-1,999999):
            with self.assertRaises(ValueError):CausalStream(minimum_response_span_us=value)
    def test_long_span_waits_for_actual_samples(self):
        for span in (200000,300000):
            view=CausalStream(minimum_response_span_us=span)
            for n in range(1,4):p=packet(n);view.telemetry(p,proof(p))
            s=packet(3);c=dict(type='gains',command_seq=1,kp=GAINS[0],ki=s['ki'],source_t_us=s['t_us'],expires_us=s['t_us']+100000)
            view.command(c,s);first=None
            for n in range(4,30):
                p=packet(n,applied_seq=1,t_apply_us=c['source_t_us']+1000);row=view.telemetry(p,proof(p))
                if row:first=row;break
            self.assertIsNotNone(first)
            self.assertGreaterEqual(first['response'][-1]['t_us']-first['response'][0]['t_us'],span)
            self.assertEqual(first['action_applied'][0],GAINS[0])
    def test_gain_change_excludes_long_partial_group(self):
        view=CausalStream(minimum_response_span_us=200000)
        for n in range(1,4):p=packet(n);view.telemetry(p,proof(p))
        s=packet(3);c=dict(type='gains',command_seq=1,kp=GAINS[0],ki=s['ki'],source_t_us=s['t_us'],expires_us=s['t_us']+100000)
        view.command(c,s)
        for n in range(4,8):p=packet(n,applied_seq=1,t_apply_us=c['source_t_us']+1000);self.assertIsNone(view.telemetry(p,proof(p)))
        view.command(dict(c,command_seq=2,kp=GAINS[1],source_t_us=p['t_us'],expires_us=p['t_us']+100000),p)
        self.assertEqual(view.rejected,1);self.assertEqual(view.windows,0)

if __name__=='__main__':unittest.main()
