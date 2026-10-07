import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from skyrim_autotest.readiness_reads import ReadinessSession
from skyrim_autotest.runner import HTTPResponseError, ToolError


class Clock:
    now = 0
    def monotonic(self): return self.now
    def sleep(self, value): self.now += value


class ReadTests(unittest.TestCase):
    def error(self, text=None, code=504):
        return HTTPResponseError(code,'api/tool/inspect',json.dumps(dict(code=code,error=text or
            'main-thread task did not start within 5000ms; queued task abandoned (170 frames elapsed -- main thread busy)')))

    def invoke(self, session, clock, name='inspect', args=None, deadline=10):
        with patch('skyrim_autotest.readiness_reads.time.monotonic',clock.monotonic), \
             patch('skyrim_autotest.readiness_reads.time.sleep',clock.sleep):
            return ReadinessSession(session,deadline).tool(name,args or {'kind':'state'},timeout=12)

    def test_exact_unstarted_read_waits_for_actual_result_same_deadline(self):
        session=SimpleNamespace(tool=Mock(side_effect=[self.error(),{'actualState':17}]),log=Mock())
        self.assertEqual(self.invoke(session,Clock()),{'actualState':17})
        self.assertEqual(session.tool.call_count,2)
        self.assertEqual([c.kwargs['deadline'] for c in session.tool.call_args_list],[10,10])
        self.assertEqual([c.kwargs['timeout'] for c in session.tool.call_args_list],[10,9.75])
        session.log.assert_called_once()

    def test_started_unknown_transport_and_server_errors_never_retried(self):
        for error in (self.error('main-thread task started but timed out'),self.error(code=500),
                      self.error('gateway timeout'),OSError('connection lost')):
            session=SimpleNamespace(tool=Mock(side_effect=error),log=Mock())
            with self.subTest(error=error),self.assertRaises(type(error)):
                self.invoke(session,Clock())
            self.assertEqual(session.tool.call_count,1)

    def test_structured_abandoned_read_allowed_but_mutations_never_replayed(self):
        args={'action':'list','includeFlags':True}
        error=ToolError('menu',args,dict(ok=False,outcome='abandoned_before_start'))
        session=SimpleNamespace(tool=Mock(side_effect=[error,{'actualMenus':[]}]),log=Mock())
        self.assertEqual(self.invoke(session,Clock(),'menu',args),{'actualMenus':[]})
        for name,args in (('menu',{'action':'close','name':'InventoryMenu'}),
                          ('game',{'action':'load','name':'owned'}),
                          ('papyrus',{'action':'call','script':'Game','function':'EnablePlayerControls'})):
            error=ToolError(name,args,dict(ok=False,outcome='abandoned_before_start'))
            session=SimpleNamespace(tool=Mock(side_effect=error),log=Mock())
            with self.subTest(name=name),self.assertRaises(ToolError):self.invoke(session,Clock(),name,args)
            self.assertEqual(session.tool.call_count,1)

    def test_persistent_abandoned_reads_exhaust_original_deadline(self):
        session=SimpleNamespace(tool=Mock(side_effect=self.error()),log=Mock());clock=Clock()
        with self.assertRaises(TimeoutError):self.invoke(session,clock,deadline=1)
        self.assertEqual(clock.now,1)
        self.assertEqual(session.tool.call_count,4)
