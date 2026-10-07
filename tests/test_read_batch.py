import threading
import time
import unittest
from unittest.mock import patch
from skyrim_autotest import read_batch


class Session:
    def __init__(self):self.state={'game':{'pid':17,'birth':123},'port':9};self.logs=[]
    def log(self,*args,**kwargs):self.logs.append((args,kwargs))


class BatchTests(unittest.TestCase):
    calls=[{'script':'SpeechBroker','function':'GetText','args':[i]} for i in range(8)]

    def test_parallel_getters_preserve_order_with_two_identity_checks(self):
        session=Session();lock=threading.Lock();active=0;maximum=0;health=0
        def request(port,path,args=None,**kwargs):
            nonlocal active,maximum,health
            if path=='api/health':health+=1;return {'pid':17}
            with lock:active+=1;maximum=max(active,maximum)
            time.sleep(.015*(4-args['args'][0]%4))
            with lock:active-=1
            return {'returned':str(args['args'][0])}
        with patch.object(read_batch.runner,'request',side_effect=request),patch.object(read_batch.native,'alive',return_value=True):
            values=read_batch.execute(session,self.calls,time.monotonic()+2)
        self.assertEqual(values,list(map(str,range(8))))
        self.assertEqual(health,2);self.assertGreater(maximum,1);self.assertLessEqual(maximum,4)
        self.assertFalse(session.logs[-1][1]['atomicSnapshot'])

    def test_arbitrary_call_or_setter_never_dispatched(self):
        for change in ({'function':'SelfTest'},{'script':'Unknown'},{'self':{},'function':'Subscribe'},{'action':'call'}):
            with patch.object(read_batch.runner,'request') as request:
                with self.assertRaises(ValueError):read_batch.execute(Session(),[dict(self.calls[0],**change)],time.monotonic()+1)
                request.assert_not_called()

    def test_identity_replacement_rejects_all_results(self):
        session=Session();health=0
        def request(port,path,args=None,**kwargs):
            nonlocal health
            if path=='api/health':health+=1;return {'pid':17 if health==1 else 18}
            return {'returned':'observed'}
        with patch.object(read_batch.runner,'request',side_effect=request),patch.object(read_batch.native,'alive',return_value=True):
            with self.assertRaisesRegex(read_batch.runner.Blocked,'identity'):read_batch.execute(session,self.calls,time.monotonic()+1)
        self.assertFalse(any(x[0]==('native-read-batch',) for x in session.logs))

    def test_expired_deadline_and_partial_failure_do_not_retry_or_accept(self):
        with patch.object(read_batch.runner,'request') as request:
            with self.assertRaises(TimeoutError):read_batch.execute(Session(),self.calls,time.monotonic()-1)
            request.assert_not_called()
        dispatched=[]
        def request(port,path,args=None,**kwargs):
            if path=='api/health':return {'pid':17}
            dispatched.append(args['args'][0]);return {'error':'unavailable'}
        with patch.object(read_batch.runner,'request',side_effect=request),patch.object(read_batch.native,'alive',return_value=True):
            with self.assertRaises(ValueError):read_batch.execute(Session(),self.calls,time.monotonic()+1)
        self.assertEqual(len(set(dispatched)),len(dispatched))


if __name__=='__main__':unittest.main()
