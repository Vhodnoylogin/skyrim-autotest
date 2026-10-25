import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import preset_domain as d

ACTOR={'reference':'0x00000014','base':'0x00000007'}
OBS={'actor':dict(ACTOR,loaded3D=True),'incarnation':{'sessionId':'s','loadGeneration':1,'runtimeHandle':9}}
ROW={'sourceMorph':'HumanTorso','targetMorph':'CLAWTorsoGirth','gain':-.5,'cap':.8}

class Backend:
    def __init__(self):
        self.calls=[]; self.result=True; self.names=['Male A']; self.status=2; self.bad=None; self.s=self
    def log(self,*a,**k):pass
    def call(self,tool,args):
        self.calls.append(('metadata',args))
        rows=[{'name':n,'params':[{'type':t} for t in ts],'returnType':rt,'native':True} for n,(ts,rt) in d.SIGNATURES.items()]
        if self.bad: self.bad(rows)
        return {'name':d.SCRIPT,'globalFunctions':rows}
    def pap(self,script,fn,values):
        self.calls.append((fn,copy.deepcopy(values)))
        if fn=='GetPresetNames': return self.names
        if fn=='GetAssigned':return 'Male A'
        if fn=='GetStatus':return self.status
        if fn=='GetLastError':return ''
        if isinstance(self.result,Exception):raise self.result
        return self.result

class Tests(unittest.TestCase):
    def setUp(self):
        self.ob=patch.object(d.actor_domain,'observe_actor',side_effect=lambda *a:copy.deepcopy(OBS));self.ob.start()
        self.an=patch.object(d.actor_domain,'anchor',return_value=(OBS['incarnation'],{},{}));self.anchor=self.an.start()
    def tearDown(self):self.ob.stop();self.an.stop()
    def req(self):return {'action':'configure-morph-link','actor':ACTOR,'profile':'fixture-v1','rows':[copy.deepcopy(ROW)]}
    def test_exact_array_order_types_and_single_mutation(self):
        b=Backend();r=d.perform(b,self.req());calls=[c for c in b.calls if c[0]=='ConfigureMorphLink']
        self.assertEqual(calls,[('ConfigureMorphLink',[{'form':ACTOR['reference']},'fixture-v1',['HumanTorso'],['CLAWTorsoGirth'],[-.5],[.8]])]);self.assertTrue(r['action']['admitted']);self.assertNotIn('completed',r['action'])
    def test_false_admission_is_retained(self):
        b=Backend();b.result=False;self.assertFalse(d.perform(b,{'action':'clear-morph-preset','actor':ACTOR})['action']['admitted'])
    def test_timeout_never_replayed(self):
        b=Backend();b.result=TimeoutError('unknown')
        with self.assertRaises(TimeoutError):d.perform(b,self.req())
        self.assertEqual(sum(c[0]=='ConfigureMorphLink' for c in b.calls),1)
    def test_wrong_mutation_return(self):
        for value in (1,None,{'queued':True}):
            b=Backend();b.result=value
            with self.assertRaises(ValueError):d.perform(b,self.req())
    def test_bad_metadata_fails_before_mutation(self):
        for bad in (lambda rows:rows.clear(),lambda rows:rows[-2].update(native=False),lambda rows:rows[-2].update(returnType='int'),lambda rows:rows[-2].update(params=[])):
            b=Backend();b.bad=bad
            with self.assertRaises((ValueError,AssertionError)):d.perform(b,self.req())
            self.assertFalse(any(c[0]=='ConfigureMorphLink' for c in b.calls))
    def test_bad_scope(self):
        b=Backend();b.call=lambda *a:{'name':d.SCRIPT,'memberFunctions':[]}
        with self.assertRaises(AssertionError):d.perform(b,self.req())
    def test_incarnation_drift(self):
        self.anchor.return_value=({'sessionId':'other'}, {}, {})
        with self.assertRaisesRegex(ValueError,'incarnation'):d.perform(Backend(),self.req())
    def test_actor_must_be_loaded(self):
        with patch.object(d.actor_domain,'observe_actor',return_value={'actor':dict(ACTOR,loaded3D=False),'incarnation':{}}):
            b=Backend()
            with self.assertRaises(ValueError):d.perform(b,self.req())
            self.assertFalse(any(c[0]=='ConfigureMorphLink' for c in b.calls))
    def test_catalog_sex_and_empty_not_availability(self):
        b=Backend();b.names=[];r=d.observe(b,{'quantity':'morph-preset-catalog','sex':'female'})
        self.assertTrue(r['catalog']['emptyAvailabilityUnknown']);self.assertIn(('GetPresetNames',[True]),b.calls)
    def test_catalog_wrong_return(self):
        for names in ('name',[True],['a','a']):
            b=Backend();b.names=names
            with self.assertRaises(ValueError):d.observe(b,{'quantity':'morph-preset-catalog','sex':'male'})
    def test_state_status_types_and_no_render_claim(self):
        b=Backend();r=d.observe(b,{'quantity':'morph-preset-state','actor':ACTOR});self.assertEqual(r['preset']['status'],2);self.assertNotIn('completed',r)
        for v in (True,8,None):
            b.status=v
            with self.assertRaises(ValueError):d.observe(b,{'quantity':'morph-preset-state','actor':ACTOR})
    def test_validate_fields_and_operation(self):
        for op in ('world.read','input.perform'):
            with self.assertRaises(ValueError):d.validate(op,self.req())
        req=self.req();req['script']='anything'
        with self.assertRaises(ValueError):d.validate('object.perform',req)
        self.assertFalse(d.validate('world.read',{'quantity':'unrelated'}))
    def test_rows_numeric_bounds_duplicates_and_feedback(self):
        badrows=[[],[ROW]*33,[ROW,ROW]]
        for field,value in [('gain',True),('gain',float('nan')),('gain',float('inf')),('cap',0),('cap',1.1),('sourceMorph','CLAWTorso')]:
            row=copy.deepcopy(ROW);row[field]=value;badrows.append([row])
        for rows in badrows:
            r=self.req();r['rows']=rows
            with self.assertRaises(ValueError):d.validate('object.perform',r)
    def test_inconsistent_caps_and_identifier_bytes(self):
        r=self.req();r['rows'].append(dict(ROW,sourceMorph='Other',cap=.7))
        with self.assertRaises(ValueError):d.validate('object.perform',r)
        for bad in ('a'*161,' a','a\n'):
            r=self.req();r['profile']=bad
            with self.assertRaises(ValueError):d.validate('object.perform',r)

class PlatformIntegrationTests(unittest.TestCase):
    def test_platform_dispatch_and_candidate_fields(self):
        import time
        from skyrim_autotest import platform
        from skyrim_autotest.platform_mapping import operations
        b=platform.Backend(Backend(),time.monotonic()+10)
        read={'quantity':'morph-preset-state','actor':ACTOR}
        write={'action':'refresh-morph-preset','actor':ACTOR}
        platform.validate({'operation':'world.read','request':read})
        platform.validate({'operation':'object.perform','request':write})
        with patch.object(d,'observe',return_value={'preset':{'status':1}}) as obs:
            self.assertEqual(b.observe(read),{'preset':{'status':1}});obs.assert_called_once_with(b,read)
        with patch.object(d,'perform',return_value={'action':{'admitted':True}}) as mutate:
            self.assertTrue(b.mutate(write)['action']['admitted']);mutate.assert_called_once_with(b,write)
        mapping=operations()
        self.assertEqual(mapping['world.read']['fields']['catalog.presetNames'],'catalog.presetNames')
        self.assertEqual(mapping['object.perform']['fields']['action.admitted'],'action.admitted')
    def test_refresh_uses_actual_metadata_and_admission_only(self):
        b=Backend()
        with patch.object(d.actor_domain,'observe_actor',return_value=copy.deepcopy(OBS)),patch.object(d.actor_domain,'anchor',return_value=(OBS['incarnation'],{},{})):
            result=d.perform(b,{'action':'refresh-morph-preset','actor':ACTOR})
        self.assertEqual([x for x in b.calls if x[0]=='Refresh'],[('Refresh',[{'form':ACTOR['reference']}])])
        self.assertEqual(result['action'],{'admitted':True})

if __name__=='__main__':unittest.main()
