import struct
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from skyrim_autotest import vr_handler_debug


class HandlerDiagnosticTests(unittest.TestCase):
    def runtime_reader(self, foreign=False):
        base=0x140000000;controls=0x200000000;handler=0x200001000
        player=0x200002000;picker=0x200004000;vr=0x200005000
        table=base+0x16F5000;route=base+0xC58000
        pointers={base+0x2F8AAA8:controls,controls+0x1A0:handler,
                  handler:base+vr_handler_debug.TABLES['ActivateHandler']+(8 if foreign else 0),
                  base+0x2FEB9F0:player,base+0x2FC60C0:picker,base+0x2FEB9B0:vr,
                  vr:table,table+0x78:route}
        def read(address,size):
            if size==8 and address in pointers:return struct.pack('<Q',pointers[address])
            if address==handler and size==0x70:
                result=bytearray(size);result[8]=1;result[0x60]=1;return bytes(result)
            if address==picker+4:return struct.pack('<3I',0,123,0)
            if size==4:return struct.pack('<I',1 if address==player+0x6D4 else 0)
            self.assertEqual((address,size),(route,4096))
            return b'\x90'*size
        return read,base

    def test_runtime_keeps_raw_flags_separate_from_non_atomic_world_proof(self):
        read,base=self.runtime_reader()
        value=vr_handler_debug.decode_runtime(read,base)
        self.assertFalse(value['atomicWorldSample'])
        self.assertEqual(value['targetHandles'],[0,123,0])
        self.assertEqual(value['handlerFlags']['0x60'],1)
        self.assertEqual(value['playerVRGrabStateRaw'],[0,0])

    def test_foreign_runtime_handler_cannot_be_interpreted_with_stock_layout(self):
        read,base=self.runtime_reader(foreign=True)
        with self.assertRaisesRegex(ValueError,'runtime table'):
            vr_handler_debug.decode_runtime(read,base)

    def reader(self, foreign=False, changing=False):
        tables={rva:0 for rva in vr_handler_debug.TABLES.values()}
        def read(address,size):
            if address in tables:
                tables[address]+=1
                value=0x1000 if not foreign else 0x3000000
                if changing and tables[address]>1:value+=8
                self.assertEqual(size,56)
                return struct.pack('<7Q',*[value]*7)
            self.assertEqual(size,4096)
            return b'\x90'*size
        return read

    def test_deduplicates_bounded_code_and_never_invokes_it(self):
        result=vr_handler_debug.decode_handlers(self.reader(),0)
        self.assertTrue(result['diagnosticOnly'])
        self.assertEqual(len(result['code']),1+len(vr_handler_debug.HELPERS))
        self.assertEqual({int(c['rva'],16) for c in result['code']},
                         {0x1000, *vr_handler_debug.HELPERS})
        self.assertEqual(len(result['code'][0]['bytesHex']),8192)

    def test_foreign_pointer_or_changed_table_is_rejected(self):
        for args in ({'foreign':True},{'changing':True}):
            with self.assertRaises(ValueError):
                vr_handler_debug.decode_handlers(self.reader(**args),0)

    def test_collector_uses_actual_session_directory_and_retains_raw_data(self):
        with tempfile.TemporaryDirectory() as directory:
            class Session:
                dir=Path(directory)
                state={'game':{'pid':1,'birth':2,'path':'owned'}}
                def log(self,*args,**kwargs):pass
            value=vr_handler_debug.decode_handlers(self.reader(),0)
            with patch.object(vr_handler_debug,'snapshot',return_value=value) as snapshot:
                vr_handler_debug.collect(Session())
            snapshot.assert_called_once_with(Session.state['game'])
            saved=json.loads((Path(directory)/'evidence/pickup-engine-handlers.json').read_text())
            self.assertEqual(saved,value)
