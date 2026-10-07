"""Deterministic frame-write contention and stale-heartbeat ordering regressions."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from skyrim_autotest import runner, hardware

class PublicationTests(unittest.TestCase):
    def test_concurrent_writers_cannot_share_or_remove_each_others_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'frame.txt'
            entered=threading.Event()
            release=threading.Event()
            started=threading.Event()
            second_wrote=threading.Event()
            errors=[]
            receipts={}
            replace=os.replace
            write=Path.write_text
            def replacing(source,destination):
                if threading.current_thread().name=='older':
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError('Test writer deadline')
                return replace(source,destination)
            def writing(path,*args,**kwargs):
                if threading.current_thread().name=='newer':
                    second_wrote.set()
                return write(path,*args,**kwargs)
            def publish(sequence):
                try:
                    if sequence==2:
                        started.set()
                    frame=hardware.neutral()
                    frame['seq']=sequence
                    hardware.publish(frame)
                    receipts[sequence]=frame['_publication']
                except Exception as error:
                    errors.append(error)
            with patch.object(hardware,'PATH',target),patch.object(hardware.os,'replace',side_effect=replacing),patch.object(Path,'write_text',writing):
                older=threading.Thread(target=publish,args=(1,),name='older')
                newer=threading.Thread(target=publish,args=(2,),name='newer')
                try:
                    older.start()
                    self.assertTrue(entered.wait(2))
                    newer.start()
                    self.assertTrue(started.wait(2))
                    self.assertFalse(second_wrote.wait(.1),'A second writer entered the shared file transaction')
                finally:
                    release.set()
                    older.join(3)
                    if newer.ident:
                        newer.join(3)
            self.assertFalse(older.is_alive() or newer.is_alive())
            self.assertEqual(errors,[])
            fields=target.read_text().split()
            self.assertEqual(fields[:2],['SKYRIM_AUTOTEST','2'])
            self.assertEqual(fields[6],receipts[2]['command'])
            self.assertEqual(int(fields[3]),receipts[2]['sequence'])
            self.assertGreater(receipts[2]['sequence'],receipts[1]['sequence'])
            self.assertFalse(target.with_suffix('.tmp').exists())
    def test_expired_heartbeat_cannot_overwrite_new_pressed_frame(self):
        class Once:
            def __init__(self):self.calls=0
            def wait(self,_):
                self.calls+=1
                return self.calls>1
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            old=hardware.neutral()
            old['seq']=1
            old['right']['controller']['pressed']=4
            session=runner.Session(folder,{'id':'test','hardwareFrame':old,'hardwareHoldUntil':0,'inputBackend':'driver','driverBackend':'file'})
            session.finished=Once()
            newer_frame=hardware.neutral()
            newer_frame['seq']=2
            newer_frame['right']['controller']['pressed']=4
            entered=threading.Event()
            release=threading.Event()
            started=threading.Event()
            errors=[]
            publish=hardware.publish
            def publishing(frame):
                if threading.current_thread().name=='heartbeat':
                    entered.set()
                    if not release.wait(3):raise RuntimeError('Test heartbeat deadline')
                return publish(frame)
            def new_input():
                started.set()
                try:session.driver_tool({'action':'publish','frame':newer_frame,'holdSeconds':10})
                except Exception as error:errors.append(error)
            def heartbeat():
                try:session.heartbeat()
                except Exception as error:errors.append(error)
            with patch.object(hardware,'PATH',folder/'frame.txt'),patch.object(hardware,'publish',side_effect=publishing),patch.object(session,'discover'):
                older=threading.Thread(target=heartbeat,name='heartbeat')
                newer=threading.Thread(target=new_input,name='new-input')
                try:
                    older.start()
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(session.state['hardwareFrame']['right']['controller']['pressed'],0)
                    newer.start()
                    self.assertTrue(started.wait(2))
                    # The previous heartbeat still holds Session.lock, so the new
                    # frame cannot be selected before the old release is written.
                    self.assertEqual(session.state['hardwareFrame']['seq'],1)
                finally:
                    release.set()
                    older.join(3)
                    if newer.ident:newer.join(3)
            self.assertFalse(older.is_alive() or newer.is_alive())
            self.assertEqual(errors,[])
            self.assertEqual(session.state['hardwareFrame']['seq'],2)
            self.assertEqual(session.state['hardwareFrame']['right']['controller']['pressed'],4)
            fields=(folder/'frame.txt').read_text().split()
            self.assertEqual(fields[:2],['SKYRIM_AUTOTEST','2'])
            self.assertEqual(fields[6],session.state['hardwareFrame']['_publication']['command'])
            self.assertEqual(int(fields[40]),4) # version2 header plus head and left values

if __name__=='__main__':unittest.main()
