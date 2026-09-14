# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic transport and decoder regression tests; no private captures."""
import json
import unittest
from pathlib import Path
from unittest import mock
import f100_readonly as m
from test_f100_readonly import _authorized_link
from test_f100_capture_session import _FakePort, _FakeSerialModule


class ReplyPort(_FakePort):
    def __init__(self, replies):
        super().__init__()
        self.replies = iter(replies)
    def write(self, data):
        result = super().write(data)
        if data != b'\0':
            self.response = next(self.replies)
        return result

class TestObservedTransport(unittest.TestCase):
    def run_request(self, replies, opcode='MQ'):
        port = ReplyPort(replies)
        link = _authorized_link(response_timeout=0.003, post_frame_quiet=0)
        with mock.patch.object(m, 'serial', _FakeSerialModule(port)), mock.patch.object(m.time, 'sleep'):
            response = link.request(opcode, live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY)
        return response, port, link

    def test_success_needs_only_one_command(self):
        response, port, _ = self.run_request([bytes.fromhex('0002611a')])
        self.assertEqual(response.status, 0x61)
        self.assertEqual(port.writes, [b'\0', b'MQ\0\0'])
        self.assertTrue(port.closed)

    def test_79_retries_exact_same_read_once_for_each_opcode(self):
        for opcode in ['MQ','CQ','OQ','LQ']:
            with self.subTest(opcode=opcode):
                response, port, link = self.run_request([bytes.fromhex('000179'), bytes.fromhex('0002611a')], opcode)
                self.assertEqual(response.status, 0x61)
                self.assertEqual(port.writes, [b'\0', opcode.encode()+b'\0\0']*2)
                link.capture.record.assert_any_call('status_79_retry', opcode=opcode, retry=1)

    def test_second_79_stops_and_is_not_success(self):
        response, port, _ = self.run_request([bytes.fromhex('000179')]*2)
        self.assertEqual(len(port.writes), 4)
        with self.assertRaises(m.ObservedNonSuccessStatus): response.require_success()

    def test_bad_or_missing_response_never_retries(self):
        for raw in [b'',bytes.fromhex('0002'),bytes.fromhex('00027900'),bytes.fromhex('0001790002611a')]:
            with self.subTest(raw=raw):
                port=ReplyPort([raw])
                link=_authorized_link(response_timeout=0.003,post_frame_quiet=0)
                with mock.patch.object(m,'serial',_FakeSerialModule(port)),mock.patch.object(m.time,'sleep'):
                    with self.assertRaises(m.ProtocolError):link.request('MQ')
                self.assertEqual(port.writes,[b'\0',b'MQ\0\0'])
                self.assertTrue(port.closed)

    def test_other_status_not_retried(self):
        response,port,_=self.run_request([bytes.fromhex('000178')])
        self.assertEqual(len(port.writes),2)
        with self.assertRaises(m.ProtocolError):response.require_success()

    def test_preflight_does_not_add_a_second_retry_layer(self):
        link=_authorized_link()
        link.request=mock.Mock(return_value=m.CameraResponse(0x79,b'',bytes.fromhex('000179')))
        with self.assertRaises(m.ObservedNonSuccessStatus):
            link.request_lq_camera_companion_preflight(live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY)
        self.assertEqual(link.request.call_count,1)



class TestAuditFollowup(unittest.TestCase):
    def test_synthetic_large_lq_default_preflight_and_direct(self):
        payload=bytes((i % 256 for i in range(1547)))  # synthetic transport bytes, not camera records
        raw=(len(payload)+1).to_bytes(2,'big')+b'\x61'+payload
        self.assertEqual(len(raw),1550)
        for preflight in [False,True]:
            with self.subTest(preflight=preflight):
                replies=[bytes.fromhex('0002611a'),bytes.fromhex('000361060a'),raw] if preflight else [raw]
                port=ReplyPort(replies)
                link=_authorized_link(response_timeout=.1,post_frame_quiet=0)
                with mock.patch.object(m,'serial',_FakeSerialModule(port)),mock.patch.object(m.time,'sleep'):
                    response=(link.request_lq_camera_companion_preflight(live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY) if preflight else link.request('LQ',live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY))
                self.assertEqual(response.data,payload)

    def test_explicit_smaller_cap_still_rejects(self):
        port=ReplyPort([bytes.fromhex('060c61')])
        link=_authorized_link(response_timeout=.1,post_frame_quiet=0)
        with mock.patch.object(m,'serial',_FakeSerialModule(port)),mock.patch.object(m.time,'sleep'):
            with self.assertRaisesRegex(m.ProtocolError,'exceeds configured maximum'):
                link.request('LQ',max_response_length=512,live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY)
        self.assertEqual(len(port.writes),2)

    def test_unknown_flash_bits_not_collapsed_to_ttl(self):
        for code in [0x07,0x0b,0x23,0x83]:
            record=bytes([1,0x42,0x30,0x50,code,0,0,0,0,0,0,0,0])
            decoded=m.decode_lq(b'\x01\xf3\x00\x01'+record+b'\x01\xfd',table_policy='raw')
            self.assertEqual(decoded['rolls'][0]['frames'][0]['flash_type'],f'unknown(0x{code:02x})')

    def test_cli_lq_default_is_protocol_limit(self):
        import argparse
        original=argparse.ArgumentParser.parse_args
        observed=[]
        class Parsed(Exception): pass
        def inspect(parser,*args,**kwargs):
            result=original(parser,['lq','--fixture','unused.hex'])
            observed.append(result.max_response_length)
            raise Parsed()
        with mock.patch.object(argparse.ArgumentParser,'parse_args',inspect):
            with self.assertRaises(Parsed):m.main()
        self.assertEqual(observed,[65535])
