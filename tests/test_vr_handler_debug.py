import struct
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from skyrim_autotest import vr_handler_debug


class HandlerDiagnosticTests(unittest.TestCase):
    def reader(self, foreign=False, changing=False):
        tables={rva:0 for rva in vr_handler_debug.TABLES.values()}
        def read(address,size):
            if address in tables:
                tables[address]+=1
                value=0x1000 if not foreign else 0x3000000
                if changing and tables[address]>1:value+=8
                return struct.pack('<5Q',*[value]*5)
            self.assertEqual(size,4096)
            return b'\x90'*size
        return read

    def test_deduplicates_bounded_code_and_never_invokes_it(self):
        result=vr_handler_debug.decode_handlers(self.reader(),0)
        self.assertTrue(result['diagnosticOnly'])
        self.assertEqual(len(result['code']),1)
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
