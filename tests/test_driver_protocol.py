import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import hardware, runner


class ProtocolTests(unittest.TestCase):
    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'frame.txt';p=patch.object(hardware,'PATH',path);p.start();self.addCleanup(p.stop)
        p=patch.object(hardware,'tick_ms',return_value=1000);p.start();self.addCleanup(p.stop)
        return path,hardware.neutral()

    def ack(self,path,frame,*,owner=None,command=None,sequence=None,mask=7,errors=0,until=6000,expired=0,at=1000):
        f=frame['_publication']
        path.with_name('ack.txt').write_text(f"SKYRIM_AUTOTEST_ACK 2 17-123 {owner or f['owner']} {sequence or f['sequence']} {command or f['command']} {at} {until} {mask} {errors} {expired}")

    def test_boot_clock_sequence_and_command_survive_process_recovery_without_wall_time(self):
        path,frame=self.fixture()
        with patch.object(hardware.time,'time',side_effect=AssertionError('wall clock used')):
            a=hardware.publish(frame);hardware._SEQUENCES.clear();b=hardware.publish(frame)
        self.assertGreater(b['sequence'],a['sequence']);self.assertEqual(b['command'],a['command'])
        self.assertEqual(path.read_text().split()[:2],['SKYRIM_AUTOTEST','2'])
        self.assertEqual(b['expiresTickMs'],6000)

    def test_ack_requires_exact_owner_command_sequence_freshness_and_all_component_roles(self):
        path,frame=self.fixture();hardware.publish(frame)
        self.ack(path,frame);self.assertTrue(hardware.acknowledgement(frame)['acknowledgedByDriver'])
        for change in ({'owner':'a'*32},{'command':'b'*32},{'sequence':1},{'until':1000},
                       {'mask':3},{'errors':4},{'expired':1},{'at':1001}):
            self.ack(path,frame,**change)
            with self.subTest(change=change):self.assertFalse(hardware.acknowledgement(frame)['acknowledgedByDriver'])

    def test_valid_component_ack_from_foreign_process_is_not_accepted_by_session(self):
        path,frame=self.fixture();hardware.publish(frame);self.ack(path,frame)
        session=runner.Session(path.parent,{'hardwareFrame':frame,'owned':[]})
        with patch('skyrim_autotest.native.identity',return_value={'pid':17,'birth':123,'path':'vrserver.exe'}):
            self.assertFalse(session.driver_acknowledgement()['acknowledgedByDriver'])
        session.state['owned']=[{'role':'vr','identity':{'pid':17,'birth':123,'path':'vrserver.exe'}}]
        with patch('skyrim_autotest.native.identity',return_value=session.state['owned'][0]['identity']):
            ack=session.driver_acknowledgement();self.assertTrue(ack['acknowledgedByDriver'])
            self.assertFalse(ack['gameConsumptionProven'])
