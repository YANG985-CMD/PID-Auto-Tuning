import unittest
from types import SimpleNamespace
import speedloop_reactive_probe as probe


class Checks(unittest.TestCase):
    def feed(self,p,seq,t,error):
        p.observe(dict(seq=seq,t_us=int(t*1000),elapsed_ms=t,enabled=True,speed_ref=1000,speed=1000-error))

    def test_hysteresis_slots_and_return(self):
        p=probe.ReactiveProbe()
        for i,t in enumerate((3860,3880,3900),1):self.feed(p,i,t,-40)
        self.assertEqual(p.planned(3900), (probe.f32(.00352456),probe.f32(.00144)))
        for i,t in enumerate(range(3920,4001,20),4):self.feed(p,i,t,50)
        self.assertEqual(p.planned(4000)[0],probe.f32(.00352456))
        for i,t in enumerate(range(4020,4161,20),9):self.feed(p,i,t,50)
        self.assertEqual(p.planned(4160)[0],probe.f32(.003389))
        self.assertEqual(p.planned(6900)[0],probe.f32(.003389))
        self.assertEqual(len(p.decisions),2)

    def test_no_future_stale_or_gap(self):
        p=probe.ReactiveProbe()
        with self.assertRaises(RuntimeError):p.planned(3900)
        for i,t in enumerate((3860,3880,3900),1):self.feed(p,i,t,-40)
        with self.assertRaises(RuntimeError):p.planned(3920)
        with self.assertRaises(RuntimeError):self.feed(p,5,3940,0)

    def test_fixed_bounds_and_startup(self):
        p=probe.ReactiveProbe()
        for t in (0,2000,3899,6900,8000):
            self.assertEqual(p.planned(t),(probe.f32(.003389),probe.f32(.00144)))
        with self.assertRaises(ValueError):p.planned(4000,1)
        with self.assertRaises(ValueError):probe.run(SimpleNamespace(authorized_reactive_probe=False))


if __name__=='__main__':unittest.main()
