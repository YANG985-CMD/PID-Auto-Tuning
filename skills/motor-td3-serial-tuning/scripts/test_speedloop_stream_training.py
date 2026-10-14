"""Stream failure gates and causality checks; no device imports or motion."""
import unittest
from speedloop_stream_training import CausalStream,KI,GAINS


def packet(seq,t=0,**changes):
    p=dict(type='telemetry',boot_id='0123456789abcdef',seq=seq,t_us=4000000+seq*20000,
        elapsed_ms=4000+seq*20,t_apply_us=4000000,applied_seq=0,enabled=True,fault=0,
        speed_ref=1000.,speed=990.,error_history=10.,integral_output=.1,current=.1,vbus=24.,
        temperature_c=None,kp=GAINS[0],ki=KI)
    p.update(changes);return p


def proof(t):
    return dict(started_us=0,run_started_us=2200000,last_us=t['t_us']+1000,
                started=1,run_seen=1,fault=0,irq_fault=0)


class Checks(unittest.TestCase):
    def prepared(self,kp=None):
        s=CausalStream()
        for n in range(1,4):p=packet(n);s.telemetry(p,proof(p))
        source=packet(3);c=dict(type='gains',command_seq=1,kp=kp or GAINS[0],ki=KI,
            source_t_us=source['t_us'],expires_us=source['t_us']+100000)
        s.command(c,source);return s,c

    def test_hold_requires_real_ack_and_four_response_packets(self):
        s,c=self.prepared()
        self.assertIsNone(s.telemetry(packet(4),proof(packet(4))))
        r=None
        for n in range(5,9):
            p=packet(n,applied_seq=1,t_apply_us=c['source_t_us']+1000);r=s.telemetry(p,proof(p))
        self.assertEqual(len(r['response']),4);self.assertEqual(r['action_applied'],[GAINS[0],KI])
        self.assertEqual(r['t_effective_us'],packet(3)['t_us'])

    def test_new_gain_response_starts_after_actual_apply(self):
        s,c=self.prepared(GAINS[1]);r=None
        for n in range(4,8):
            p=packet(n,kp=GAINS[1],applied_seq=1,t_apply_us=c['source_t_us']+1000);r=s.telemetry(p,proof(p))
        self.assertEqual(r['t_effective_us'],c['source_t_us']+1000)
        self.assertAlmostEqual(r['physical_delta_action'][0],.5,places=6)

    def test_fault_gap_and_unknown_ack_are_rejected(self):
        for p in (packet(4,fault=8),packet(5),packet(4,applied_seq=2)):
            s,_=self.prepared()
            with self.assertRaises(ValueError):s.telemetry(p,proof(p))

    def test_gain_change_excludes_partial_response(self):
        s,c=self.prepared();p=packet(4,applied_seq=1,t_apply_us=c['source_t_us']+1000)
        s.telemetry(p,proof(p));s.command(dict(c,command_seq=2,kp=GAINS[1],source_t_us=p['t_us']),p)
        self.assertEqual(s.rejected,1);self.assertEqual(s.windows,0)

    def test_missing_stage_proof_and_boot_change_are_rejected(self):
        s,c=self.prepared();p=packet(4,applied_seq=1,t_apply_us=c['source_t_us']+1000)
        with self.assertRaises(ValueError):s.telemetry(p,None)
        s,c=self.prepared();p=packet(4,boot_id='fedcba9876543210')
        with self.assertRaises(ValueError):s.telemetry(p,proof(p))

    def test_unexplored_ki_rejected(self):
        s,c=self.prepared();p=packet(4)
        with self.assertRaises(ValueError):s.command(dict(c,command_seq=2,ki=KI*1.01,source_t_us=p['t_us']),p)


if __name__=='__main__':unittest.main()
