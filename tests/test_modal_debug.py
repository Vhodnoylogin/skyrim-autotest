"""Duplicate notifications require queue identity, not repeated similar text."""
import struct
import unittest
from skyrim_autotest.modal_debug import decode_queue


class ModalQueueTests(unittest.TestCase):
    def fixture(self):
        memory={0x10000:struct.pack('<QIIII',0x20000,2,0,2,0),
                0x20000:struct.pack('<QQ',0x30000,0x40000)}
        for identity, text, button in ((0x30000,0x50000,0x60000),(0x40000,0x70000,0x80000)):
            data=bytearray(80)
            data[16:32]=struct.pack('<QHHI',text,4,4,0)
            data[32:56]=struct.pack('<QIIII',button,1,0,1,0)
            struct.pack_into('<i',data,60,-1)
            memory[identity]=bytes(data);memory[text]=b'Same\0'
            memory[button]=struct.pack('<QHHI',button+32,2,2,0)
            memory[button+32]=b'OK\0'
        return memory
    def test_identical_text_does_not_merge_distinct_queued_notifications(self):
        memory=self.fixture()
        value=decode_queue(lambda address,size:memory[address][:size],0x10000)
        self.assertEqual(value['depth'],2)
        self.assertEqual([x['bodyText'] for x in value['queued']],['Same','Same'])
        self.assertEqual([x['id'] for x in value['queued']],['0x30000','0x40000'])
    def test_queue_change_cannot_be_reported_as_coherent(self):
        memory=self.fixture();reads=[]
        def read(address,size):
            reads.append(address)
            if address==0x10000 and reads.count(address)>1:
                return struct.pack('<QIIII',0x20000,2,0,1,0)
            return memory[address][:size]
        with self.assertRaisesRegex(ValueError,'changed during'):
            decode_queue(read,0x10000)
    def test_invalid_header_stops_before_following_any_pointer(self):
        reads=[]
        def read(address,size):
            reads.append(address)
            return struct.pack('<QIIII',0x20000,2,0,1000,0)
        with self.assertRaisesRegex(ValueError,'array layout'):
            decode_queue(read,0x10000)
        self.assertEqual(reads,[0x10000])


if __name__=='__main__':unittest.main()
