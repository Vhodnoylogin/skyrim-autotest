import copy,time,unittest
from unittest.mock import patch
from skyrim_autotest import platform
from skyrim_autotest.hardware import neutral


class ReleaseHandTests(unittest.TestCase):
    def test_release_only_selected_hand_without_reapproach_or_pose_changes(self):
        for hand in ['left','right']:
            frame=neutral();frame[hand]['matrix'][3]=.45;frame[hand]['controller']['pressed']=4
            other='left' if hand=='right' else 'right';frame[other]['controller']['pressed']=6
            original=copy.deepcopy(frame)
            class Session:
                state={'hardwareFrame':frame}
                def log(self,*args,**kwargs):pass
            b=platform.Backend(Session(),time.monotonic()+5);calls=[]
            b.call=lambda tool,args:calls.append((tool,args)) or {'messageBoxOpen':False,'openMenus':[],'menuStates':[]} if tool=='menu' else {}
            publications=[];b.publish=lambda value,duration:publications.append(copy.deepcopy(value)) or {'published':True}
            b.pause=lambda seconds:None
            req={'action':'release_hand','hand':hand,'settleSeconds':1.2}
            platform.validate({'operation':'controller.perform','request':req})
            with patch('skyrim_autotest.vr_probe.ensure_owned_focus'),patch('skyrim_autotest.body_scene.pose',side_effect=AssertionError('no reapproach')):
                result=b.controller(req)
            self.assertTrue(result['inputIssued']);self.assertIsNone(result['observedGameplaySuccess'])
            self.assertEqual(len(publications),1)
            out=publications[0];self.assertEqual(out[hand]['controller']['pressed'],0)
            self.assertEqual(out[hand]['matrix'],original[hand]['matrix'])
            self.assertEqual(out[other],original[other]);self.assertEqual(out['hmd'],original['hmd'])
            self.assertEqual(frame,original)

    def test_invalid_release_request_rejected(self):
        for change in [{'hand':'both'},{'settleSeconds':11},{'trackingPosition':[0,0,0]}]:
            req={'action':'release_hand','hand':'left','settleSeconds':1};req.update(change)
            with self.assertRaises(ValueError):platform.validate({'operation':'controller.perform','request':req})
