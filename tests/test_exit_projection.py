"""Actual VR13b retained sequence and identity/quality counterexamples; no live calls."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from skyrim_autotest.exit_projection import terminal_exit_observation as select
from skyrim_autotest import runner
FIXTURE=json.loads((HERE/'fixtures/vr13b-exit-observations.json').read_bytes())

class ExitProjectionTests(unittest.TestCase):
    def setUp(self):
        self.game=copy.deepcopy(FIXTURE['game']);self.rows=copy.deepcopy(FIXTURE['gameProcessObservations'])
        self.known=next(copy.deepcopy(r) for r in reversed(self.rows) if r['status']=='exited')
    def test_actual13b_later_unavailable_cannot_erase_retained_handle_code(self):
        before=copy.deepcopy(self.rows);self.assertEqual(self.rows[-1]['status'],'unavailable')
        result=select(self.rows,self.game)
        self.assertEqual(result,self.known);self.assertEqual(result['exitCode'],0);self.assertEqual(self.rows,before)
        result['identity']['pid']=1;self.assertEqual(self.rows,before)
    def test_different_pid_birth_or_path_is_not_merged(self):
        for key,value in [('pid',self.game['pid']+1),('birth',self.game['birth']+1),('path',self.game['path'].lower())]:
            expected=dict(self.game,**{key:value})
            with self.subTest(key=key):self.assertIsNone(select(self.rows,expected))
    def test_both_identity_brackets_must_match_expected_exactly(self):
        for field in ['identity','expectedIdentity']:
            row=copy.deepcopy(self.known);row[field]['birth']+=1
            with self.subTest(field=field):self.assertIsNone(select([row],self.game))
    def test_unverified_nonretained_or_unavailable_exit_does_not_qualify(self):
        for field in ['identityVerified','handleRetained','exitCodeAvailable']:
            for value in [False,None,1]:
                row=dict(self.known,**{field:value})
                with self.subTest(field=field,value=value):self.assertIsNone(select([row],self.game))
    def test_invalid_code_status_schema_and_hex_refuse(self):
        for change in [{'exitCode':True},{'exitCode':-1},{'exitCode':2**32},{'status':'running'},{'schemaVersion':True},{'schemaVersion':2},{'exitCodeHex':'0xDEADBEEF'}]:
            with self.subTest(change=change):self.assertIsNone(select([dict(self.known,**change)],self.game))
    def test_missing_or_malformed_identity_is_not_guessed(self):
        for value in [None,{},dict(self.game,birth=True),dict(self.game,path=''),dict(self.game,extra='unknown')]:
            with self.subTest(value=value):self.assertIsNone(select(self.rows,value))
        self.assertIsNone(select(None,self.game));self.assertIsNone(select([None,{}],self.game))
    def test_conflicting_trusted_exit_codes_refuse_selection(self):
        conflict=dict(self.known,exitCode=42,exitCodeHex='0x0000002A')
        self.assertIsNone(select([self.known,conflict,self.rows[-1]],self.game))
    def report(self,rows):
        state={'id':'vr13b-projection-fixture','configuration':{'game_edition':'vr'},'preflight':{'profile':'fixture'},
               'game':self.game,'result':'failed','restored':True,'reason':FIXTURE['terminationContext'],
               'checks':[],'gameProcessObservations':rows,'forcedGameStop':False,
               'gameTermination':{'kind':'external_forced_stop','source':'Retained SteamVR kill log; exit0 is not normal'}}
        with tempfile.TemporaryDirectory() as temp:
            # Exercise the actual report method without admitting a Session/configuration.
            session=runner.Session.__new__(runner.Session);session.dir=Path(temp);session.state=state
            before=copy.deepcopy(state);session.report()
            text=(Path(temp)/'report.md').read_text(encoding='utf8');result=json.loads((Path(temp)/'result.json').read_bytes())
            self.assertEqual(state,before)
            return text,result
    def test_actual_report_retains_known_exit_and_later_recovery_diagnostic(self):
        text,result=self.report(self.rows)
        self.assertIn('Exit code: 0x00000000',text);self.assertIn('Latest recovery observation: unavailable',text)
        self.assertIn('does not determine the exit cause or prove an unforced exit',text)
        self.assertEqual(result['gameProcessObservations'],self.rows);self.assertEqual(result['result'],'failed')
        self.assertEqual(result['gameTermination']['kind'],'external_forced_stop')
        self.assertNotIn('normal_close',json.dumps(result));self.assertEqual(result['reason'],FIXTURE['terminationContext'])
    def test_actual_report_does_not_publish_unverified_exit_code(self):
        row=dict(self.known,identityVerified=False);text,result=self.report([row])
        self.assertIn('Exit code: unavailable',text);self.assertEqual(result['gameProcessObservations'],[row])
    def test_actual_report_without_observations_keeps_legacy_shape(self):
        text,result=self.report([]);self.assertNotIn('## Game process observation',text)
        self.assertEqual(result['gameProcessObservations'],[])
if __name__=='__main__':unittest.main()
