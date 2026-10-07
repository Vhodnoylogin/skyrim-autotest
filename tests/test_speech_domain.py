import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import speech_domain as domain, platform

START = 'self-test token {0}'
OK = 'self-test token {0} answered in {1} ms'
def line(message): return '[2026-10-07 16:00:00.001] [global log] [info] '+message+'\n'


class Session:
    def __init__(self): self.state = {'game': {'pid': 10, 'birth': 200, 'path': 'owned'}}; self.saves = 0
    def save(self): self.saves += 1
    def log(self, *a, **kw): pass


class Backend:
    def __init__(self, path=None): self.s = Session(); self.path = path; self.calls = []; self.values = {}; self.fail = False
    def pap(self, script, function, args=None):
        self.calls.append((script, function, args))
        if function == 'Translate': return START if args[0].endswith('_START') else OK
        if function == 'SelfTest':
            if self.fail: raise TimeoutError('mutation may still run')
            with self.path.open('a', encoding='utf-8') as f: f.write(line('self-test token 7'))
            return None
        return self.values.get((function, tuple(args or [])), self.values.get(function))


class SpeechDomainTests(unittest.TestCase):
    def test_roundtrip_requires_new_correlated_native_pong(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'SpeechBroker.log'; path.write_text(line('old token 6'), encoding='utf-8')
            b = Backend(path)
            with patch.object(domain, 'log_file', return_value=path):
                domain.perform(b, {'action': domain.ACTION})
                self.assertFalse(domain.roundtrip(b)['speech']['events']['roundtripCompleted'])
                with path.open('a', encoding='utf-8') as f: f.write(line('self-test token 6 answered in 12 ms'))
                self.assertFalse(domain.roundtrip(b)['speech']['events']['roundtripCompleted'])
                with path.open('a', encoding='utf-8') as f: f.write(line('self-test token 7 answered in 15 ms'))
                self.assertTrue(domain.roundtrip(b)['speech']['events']['roundtripCompleted'])
                with self.assertRaisesRegex(ValueError, 'never replay'): domain.perform(b, {'action': domain.ACTION})
                self.assertEqual(sum(c[1]=='SelfTest' for c in b.calls), 1)

    def test_mutation_timeout_retains_intent_and_no_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'log'; path.write_bytes(b''); b = Backend(path); b.fail = True
            with patch.object(domain, 'log_file', return_value=path):
                with self.assertRaises(TimeoutError): domain.perform(b, {})
                with self.assertRaises(ValueError): domain.perform(b, {})
                self.assertEqual(b.s.state['speechRoundtrip']['status'], 'requesting')
                self.assertEqual(sum(c[1]=='SelfTest' for c in b.calls), 1)

    def test_log_rotation_and_game_replacement_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'log'; path.write_text('existing\n', encoding='utf-8'); b = Backend(path)
            with patch.object(domain, 'log_file', return_value=path):
                domain.perform(b, {})
                saved = copy.deepcopy(b.s.state)
                b.s.state['game']['birth'] += 1
                with self.assertRaisesRegex(ValueError, 'identity'): domain.roundtrip(b)
                b.s.state = saved; path.write_bytes(b'')
                with self.assertRaisesRegex(ValueError, 'rotated'): domain.roundtrip(b)

    def test_overlapping_request_not_correlated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'log'; path.write_bytes(b''); b = Backend(path)
            with patch.object(domain, 'log_file', return_value=path):
                domain.perform(b, {})
                with path.open('a', encoding='utf-8') as f: f.write(line('self-test token 8'))
                with self.assertRaisesRegex(ValueError, 'Overlapping'): domain.roundtrip(b)

    def test_recognition_and_awards_exact_nonempty_strict_predicate(self):
        b = Backend(); b.values = {('GetText',(1,)):'heard',('GetText',(2,)):'',('GetText',(3,)):'boundary',
            ('GetVocabularyScore',(1,'DemoGreedy')):.6,('GetVocabularyScore',(3,'DemoGreedy')):.5,
            ('IsWinner',(1,'DemoGreedy')):True,('IsWinner',(3,'DemoGreedy')):True}
        req = {'observation':'speech.door_recognition','idRange':{'first':1,'last':3},'namespace':'DemoGreedy','minimumVocabularyScoreExclusive':.5}
        self.assertEqual(domain.observe(b, req)['speech']['recognition']['doorTextCount'],1)
        req['observation']='speech.door_awards'
        self.assertEqual(domain.observe(b, req)['speech']['auction']['doorGreedyAwardCount'],1)
        self.assertFalse(any(c[1] in ('Bid','PushUtterance','Subscribe','RegisterVocabulary') for c in b.calls))
        b.values[('IsWinner',(1,'DemoGreedy'))] = None
        with self.assertRaisesRegex(ValueError,'winner'):domain.observe(b,req)

    def test_provider_types_do_not_default_on_absence(self):
        b = Backend(); b.values = {'IsAvailable':True,'GetInterfaceVersion':3,'GetAdapters':['voice'],'GetSource':'voice'}
        self.assertEqual(domain.observe(b,{'observation':'speech.broker.status'})['speech']['broker']['interfaceVersion'],3)
        b.values['GetAdapters']=None
        with self.assertRaises(ValueError):domain.observe(b,{'observation':'speech.broker.status'})
        with self.assertRaises(ValueError):domain.number(True,0,1)

    def test_log_template_matches_entire_message_not_recognized_text(self):
        pattern=domain.template_pattern(OK)
        self.assertEqual(len(list(pattern.finditer(line('self-test token 7 answered in 1 ms')))),1)
        self.assertFalse(pattern.search(line('recognized text: self-test token 7 answered in 1 ms')))

    def test_validation_preserves_range_and_predicate(self):
        req={'observation':'speech.door_awards','idRange':{'first':1,'last':16},'namespace':'DemoGreedy','minimumVocabularyScoreExclusive':.5}
        platform.validate({'operation':'world.read','request':req})
        for bad in ({'first':0,'last':16},{'first':1,'last':17},{'first':True,'last':1}):
            with self.assertRaises(ValueError):domain.validate('world.read',dict(req,idRange=bad))
        with self.assertRaises(ValueError):domain.validate('object.perform',req)
        with self.assertRaises(ValueError):domain.validate('object.perform',{'action':domain.ACTION,'count':True,'target':'speech-broker'})


if __name__ == '__main__':unittest.main()
