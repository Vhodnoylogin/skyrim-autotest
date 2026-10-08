import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import tracking_basis as domain,hardware


class Backend:
    def __init__(self):
        self.s=self;self.clock=0.;self.frames=[];self.logs=[];self.pose=hardware.neutral()
        self.consume=True;self.scale=[70,70,70];self.handle=7;self.lose=False
        self.wrong_name=False;self.common=0.;self.disagree=False
    def guard_world(self):pass
    def log(self,*args,**kw):self.logs.append((args,kw))
    def remaining(self):return 20-self.clock
    def pause(self,n):self.clock+=n
    def pap(self,*args):
        return None if args[-1][0] or (self.lose and self.frames) else {'formId':'0xFF000123'}
    def publish(self,frame,duration):
        self.frames.append(copy.deepcopy(frame))
        if self.consume:self.pose=copy.deepcopy(frame)
        return {}
    def call(self,tool,args):
        nodes=[]
        for query in args['nodes']:
            # Deliberately unrelated, nonlinear FP skeletal response.
            point=[9999*self.clock,500*self.clock*self.clock,-10000] if query['firstPerson'] else [0,0,100]
            nodes.append(dict(query,form='0x14',status='available',
                identity={'form':'0x14','loadGeneration':1,'runtimeHandle':self.handle},world={'translation':point}))
        rig={}
        for role,key,name in [('hmd','uprightHmd','UprightHmdNode'),('left','leftWand','LeftWandNode'),('right','rightWand','RightWandNode')]:
            point=[self.pose[role]['matrix'][i]*scale for i,scale in zip((3,7,11),self.scale)]
            point[0]+=self.common if role!='right' else 0
            if self.disagree and role=='hmd':point[0]+=1
            rig[key]={'status':'available','name':'WrongNode' if self.wrong_name else name,'world':{'translation':point}}
        return {'ok':True,'space':'world','units':'skyrim_engine_units','sessionId':'S','loadGeneration':1,
                'nodes':nodes,'vrPicking':{'status':'available','space':'world','units':'skyrim_engine_units','nodes':rig}}


class TrackingBasisTests(unittest.TestCase):
    def run_calibration(self,b):
        frame=hardware.neutral();frame['right']['controller']['pressed']=4
        frame['left']['controller']['pressed']=4
        b.pose=copy.deepcopy(frame)
        with patch.object(domain.time,'monotonic',side_effect=lambda:b.clock):
            result=domain.calibrate(b,frame,'right')
        return result,frame

    def test_native_metric_independent_of_nonlinear_held_hand_response(self):
        b=Backend();(columns,baseline),frame=self.run_calibration(b)
        for actual,wanted in zip(columns,[[70,0,0],[0,70,0],[0,0,70]]):
            for a,c in zip(actual,wanted):self.assertAlmostEqual(a,c)
        self.assertEqual(len(b.frames),6)
        for f in b.frames:
            self.assertEqual(f['hmd'],frame['hmd']);self.assertEqual(f['left'],frame['left'])
            self.assertEqual(f['right']['controller'],frame['right']['controller'])
        self.assertEqual(b.frames[-1],frame)
        self.assertTrue(all(not kw['skeletalResponseUsedAsMetric'] for args,kw in b.logs if args==('platform-native-tracking-calibration',)))

    def test_unconsumed_probe_stops_without_return_or_replay(self):
        b=Backend();b.consume=False
        with self.assertRaisesRegex(ValueError,'consumption unavailable'):self.run_calibration(b)
        self.assertEqual(len(b.frames),1)

    def test_missing_native_rig_never_falls_back_to_hand(self):
        b=Backend();b.wrong_name=True
        with self.assertRaisesRegex(ValueError,'Exact native'):self.run_calibration(b)
        self.assertFalse(b.frames)

    def test_lost_held_source_stops_before_next_publication(self):
        b=Backend();b.lose=True
        with self.assertRaisesRegex(ValueError,'Held reference changed'):self.run_calibration(b)
        self.assertEqual(len(b.frames),1)

    def test_changed_incarnation_cannot_supply_probe(self):
        b=Backend();old=b.publish
        def publish(*args):old(*args);b.handle+=1
        b.publish=publish
        with self.assertRaisesRegex(ValueError,'incarnation changed'):self.run_calibration(b)
        self.assertEqual(len(b.frames),1)

    def test_disagreeing_or_moving_unchanged_devices_cannot_supply_metric(self):
        for attr in ('common','disagree'):
            b=Backend();old=b.publish
            def publish(*args):old(*args);setattr(b,attr,1.)
            b.publish=publish
            with self.subTest(attr=attr),self.assertRaisesRegex(ValueError,'native|Native'):self.run_calibration(b)
            self.assertEqual(len(b.frames),1)

    def test_nonrigid_native_axes_refused(self):
        b=Backend();b.scale=[70,140,70]
        with self.assertRaisesRegex(ValueError,'nonrigid'):self.run_calibration(b)


if __name__=='__main__':unittest.main()
