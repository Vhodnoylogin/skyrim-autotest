import unittest
from skyrim_autotest import api_contract


class ApiContractTests(unittest.TestCase):
    def test_extension_schema_qualifies_refs_independently_of_host_core_inspect(self):
        descriptor={'readOnly':True,'inputSchema':{'properties':{
            'kind':{'const':'world_observer'},'refs':{'type':'array','maxItems':16}}}}
        self.assertEqual(api_contract.validate_observer_descriptor({'extensions':[
            {'kind':'world_observer','descriptor':descriptor}]}),descriptor)
    def test_missing_duplicate_or_undeclared_observer_query_stops_before_request(self):
        for entries in ([],[{'kind':'world_observer','descriptor':{}}],
                        [{'kind':'world_observer'},{'kind':'world_observer'}]):
            with self.subTest(entries=entries),self.assertRaises(AssertionError):
                api_contract.validate_observer_descriptor({'extensions':entries})
    def test_supported_native_signature_is_read_from_live_metadata(self):
        metadata={'name':'ObjectReference','memberFunctions':[
            {'name':'SetPosition','params':[{'type':'Float','name':v} for v in ('afX','afY','afZ')],
             'returnType':'None','native':True}]}
        checked=api_contract.validate_description('ObjectReference',metadata,'memberFunctions',
                                                    {'SetPosition':['float']*3})
        self.assertEqual(len(checked),1)
        self.assertEqual(checked[0]['params'][2]['name'],'afZ')

    def test_old_nonexistent_per_axis_setter_fails_before_any_call(self):
        metadata={'name':'ObjectReference','memberFunctions':[
            {'name':'SetPosition','params':[{'type':'Float'}]*3}]}
        with self.assertRaisesRegex(AssertionError,'missing ObjectReference.SetPositionX'):
            api_contract.validate_description('ObjectReference',metadata,'memberFunctions',{'SetPositionX':['float']})

    def test_wrong_scope_identity_and_parameter_types_are_rejected(self):
        for value in [
            {'name':'Actor','memberFunctions':[]},
            {'name':'ObjectReference','globalFunctions':[]},
            {'name':'ObjectReference','memberFunctions':[{'name':'SetPosition','params':[{'type':'Bool'}]*3}]},
        ]:
            with self.subTest(value=value),self.assertRaises(AssertionError):
                api_contract.validate_description('ObjectReference',value,'memberFunctions',{'SetPosition':['float']*3})

    def test_qualification_failure_is_read_only_and_never_marks_api_ready(self):
        class Session:
            state={}
            def __init__(self):self.calls=[]
            def phase(self,*a):pass
            def tool(self,name,args):
                self.calls.append((name,args));return {'name':args['script'],'memberFunctions':[]}
        session=Session()
        with self.assertRaises(AssertionError):api_contract.qualify(session,mobility=True)
        self.assertTrue(all(name=='papyrus' and args['action']=='describe' for name,args in session.calls))
        self.assertNotIn('livePapyrusApi',session.state)
