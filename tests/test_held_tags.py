import copy
import time
import unittest
from types import SimpleNamespace
from skyrim_autotest.platform import Backend, validate


class HeldTagTests(unittest.TestCase):
    def backend(self):
        self.ref='0xFF001234'
        self.snapshot={'ok':True,'sessionId':'session-a','loadGeneration':2,'sampleId':7,
                       'refs':[{'status':'available','loaded3D':True,'deleted':False,'disabled':False,
                                'identity':{'form':self.ref,'runtimeHandle':91,'loadGeneration':2}}]}
        self.held=[{'formId':self.ref},{'formId':self.ref}]
        session=SimpleNamespace(state={'platformReferences':{'old-seed':{'id':self.ref}}},
                                save=lambda:None,log=lambda *a,**k:None,
                                validate_probe_reference=lambda **k:None)
        backend=Backend(session,time.monotonic()+30)
        backend.call=lambda tool,args:copy.deepcopy(self.snapshot)
        backend.pap=lambda *a,**k:self.held.pop(0)
        return backend

    def req(self):return {'action':'tag_held_reference','hand':'right','referenceTag':'drawn-outside'}

    def test_tag_actual_held_handle_instead_of_assuming_old_seed_form_id(self):
        b=self.backend();validate({'operation':'object.perform','request':self.req()})
        value=b.mutate(self.req())
        self.assertEqual(value['reference']['id'],self.ref)
        self.assertEqual(value['reference']['incarnation']['runtimeHandle'],91)
        self.assertEqual(b.tagged(self.req()),self.ref)
        # Identical recycled formID with a different native handle must fail.
        self.snapshot['refs'][0]['identity']['runtimeHandle']=92
        with self.assertRaisesRegex(ValueError,'incarnation'):b.tagged(self.req())

    def test_bracketed_hand_change_or_missing_handle_does_not_create_a_tag(self):
        for failure in ('changed','empty','missing-handle'):
            b=self.backend()
            if failure=='changed':self.held[1]={'formId':'0xFF009999'}
            elif failure=='empty':self.held[0]=None
            else:self.snapshot['refs'][0]['identity']['runtimeHandle']=0
            with self.subTest(failure=failure),self.assertRaises(ValueError):b.mutate(self.req())
            self.assertNotIn('drawn-outside',b.s.state['platformReferences'])

    def test_tag_cannot_be_reused_and_session_or_load_changes_invalidate_identity(self):
        b=self.backend();b.mutate(self.req())
        with self.assertRaisesRegex(ValueError,'already used'):b.mutate(self.req())
        self.snapshot['sessionId']='session-b'
        with self.assertRaisesRegex(ValueError,'incarnation'):b.tagged(self.req())
        self.snapshot['sessionId']='session-a';self.snapshot['loadGeneration']=3
        self.snapshot['refs'][0]['identity']['loadGeneration']=3
        with self.assertRaisesRegex(ValueError,'incarnation'):b.tagged(self.req())


if __name__=='__main__':unittest.main()
