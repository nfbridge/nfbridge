# SPDX-License-Identifier: GPL-3.0-only
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mac-client'))
import f100_maintenance as mt
import f100_readonly as ro
from test_guided import snapshots, connection, binding
from test_transport_regressions import ReplyPort
from test_f100_capture_session import _FakeSerialModule

DATA=bytes.fromhex('00f3000101361a420013fd')

def response(payload):return (len(payload)+1).to_bytes(2,'big')+b'\x61'+payload

def state(mq,payload):return [response(bytes([mq])),response((len(payload)-1).to_bytes(2,'big')),response(payload)]

class WorkflowCamera:
    def __init__(self):self.mq=0x13;self.data=DATA;self.writes=[];self.capture=mock.Mock();self.bad_erase=False
    def request(self,opcode,**kw):
        payload={'MQ':bytes([self.mq]),'OQ':(len(self.data)-1).to_bytes(2,'big'),'LQ':self.data}[opcode]
        return ro.CameraResponse(0x61,payload,response(payload))
    def arm(self,*args):pass
    def mutate(self,opcode,payload):
        self.writes.append((opcode,payload))
        if opcode=='EP' and not self.bad_erase:self.data=b'\0';self.mq=3
        if opcode=='NP':self.mq=payload[0];self.data=b'\1'

class MaintenanceTests(unittest.TestCase):
    def test_backup_before_confirmation_preserves_policy_and_post_ep_bits(self):
        cam=WorkflowCamera()
        with tempfile.TemporaryDirectory() as d:
            def yes(action,details):
                self.assertEqual((Path(d)/'backup-lq.bin').read_bytes(),DATA)
                return True
            result=mt.run(cam,d,yes,actor='user',channel='terminal')
            self.assertEqual(result['status'],'verified')
            self.assertEqual(cam.writes,[('EP',b''),('NP',b'\x0b')])
    def test_cancel_has_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            cam=WorkflowCamera();result=mt.run(cam,d,lambda *_:False,actor='user',channel='terminal')
            self.assertEqual(cam.writes,[]);self.assertEqual(result['status'],'cancelled_before_erase')
    def test_backup_failure_prevents_confirmation_and_writes(self):
        with tempfile.TemporaryDirectory() as d:
            cam=WorkflowCamera();confirm=mock.Mock()
            with mock.patch.object(mt,'save_new',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):mt.run(cam,d,confirm,actor='user',channel='terminal')
            confirm.assert_not_called();self.assertEqual(cam.writes,[])
    def test_changed_camera_after_review_prevents_erase(self):
        with tempfile.TemporaryDirectory() as d:
            cam=WorkflowCamera()
            def change(*_):cam.data=b'\0';return True
            with self.assertRaises(ro.ProtocolError):mt.run(cam,d,change,actor='user',channel='terminal')
            self.assertEqual(cam.writes,[])
    def test_erase_ack_without_empty_memory_blocks_np(self):
        with tempfile.TemporaryDirectory() as d:
            cam=WorkflowCamera();cam.bad_erase=True
            with self.assertRaises(ro.ProtocolError):mt.run(cam,d,lambda *_:True,actor='user',channel='terminal')
            self.assertEqual(cam.writes,[('EP',b'')])
    def test_cancel_settings_after_erase(self):
        with tempfile.TemporaryDirectory() as d:
            cam=WorkflowCamera();result=mt.run(cam,d,lambda action,_:action=='erase',actor='user',channel='terminal')
            self.assertEqual(result['status'],'erased_settings_unchanged');self.assertEqual(cam.writes,[('EP',b'')])
    def test_readonly_api_still_rejects_writes(self):
        for op in ('EP','NP','DP'):
            with self.assertRaises(ro.ProtocolError):ro.encode_request(op)
    def execute_cli(self,replies,answers=('y','y','y'),short_ep=False):
        before,after=snapshots()
        with tempfile.TemporaryDirectory() as d:
            session,port=connection.prepare(d,'maintenance-test',before,after,user_confirmed=True)
            planpath=session/'orchestration-plan.json';plan=json.loads(planpath.read_text())
            plan.update(mac_command='maintenance',np_dp_ep_implemented=True,dp_implemented=False,maintenance_action=mt.ACTION,automatic_write_retry=False)
            plan.pop('plan_sha256_without_this_field');plan['plan_sha256_without_this_field']=connection.gate._canonical_hash(plan);planpath.write_text(json.dumps(plan))
            connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
            fake=ReplyPort(replies)
            if short_ep:
                original_write=fake.write
                def short_write(data):
                    if data==b"EP\0\0":
                        fake.writes.append(data);return 1
                    return original_write(data)
                fake.write=short_write
            args=['maintenance','--port',port,'--integration-session-id',session.name,'--orchestration-plan',str(planpath),'--admission-report',str(session/'mac-admission/report.json'),'--utm-forwarding-gate',str(session/'mac-admission/utm-forwarding-gate.json'),'--capture-dir',str(session/'mac-client/capture'),'--execute-erase-and-detailed']
            with mock.patch.object(sys,'argv',args),mock.patch.object(ro,'serial',_FakeSerialModule(fake)),mock.patch.object(ro.time,'sleep'),mock.patch('builtins.input',side_effect=answers),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=mt.main()
            manifest=json.loads((session/'mac-client/capture/session-manifest.json').read_text())
            return result,fake.writes,manifest
    def test_real_cli_binding_transport_and_capture(self):
        replies=state(0x12,DATA)*2+[response(b'')]+state(2,b'\0')*2+[response(b'')]+state(0x0a,b'\1')
        result,writes,manifest=self.execute_cli(replies)
        self.assertEqual(result,0);self.assertEqual(writes.count(b'EP\0\0'),1);self.assertEqual(writes.count(b'NP\0\1\x0a'),1)
        self.assertEqual(manifest['operation_scope'],mt.ACTION);self.assertFalse(manifest['dp_implemented']);self.assertEqual(manifest['outcome'],'success')
    def test_write_79_is_not_retried(self):
        result,writes,manifest=self.execute_cli(state(0x12,DATA)*2+[bytes.fromhex('000179')])
        self.assertEqual(result,2);self.assertEqual(writes.count(b'EP\0\0'),1)
        self.assertFalse(any(x.startswith(b'NP') for x in writes));self.assertEqual(manifest['outcome'],'failure')

    def test_cli_user_declines_erase_or_e_is_interrupted_not_failure(self):
        for replies,answers,erased in ((state(0x12,DATA),('n',),False),
                (state(0x12,DATA)*2+[response(b'')]+state(2,b'\0'),('y','y','n'),True)):
            with self.subTest(erased=erased):
                result,writes,manifest=self.execute_cli(replies,answers=answers)
                self.assertEqual(result,0)
                self.assertEqual(manifest['outcome'],'interrupted')
                self.assertEqual(writes.count(b'EP\0\0'),int(erased))
                self.assertFalse(any(x.startswith(b'NP') for x in writes))
    def test_maintenance_plan_preview_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            p=connection.orchestrator.create_plan(argparse.Namespace(root=Path(d),session_id='maint-plan',mode='mac-client',program=None,guest_com=None,serial_port='/dev/cu.fixture',vm_pty=None,mac_command='maintenance'))
            plan=json.loads(p.read_text());self.assertEqual(plan['maintenance_action'],mt.ACTION)
            self.assertIn('f100_maintenance.py',plan['commands']['mac_client_preview_only'])
            self.assertNotIn('f100_readonly.py',plan['commands']['mac_client_preview_only'])

    def test_np_ack_followed_by_wrong_mode_is_failure(self):
        replies=state(0x12,DATA)*2+[response(b'')]+state(2,b'\0')*2+[response(b'')]+state(2,b'\0')
        result,writes,manifest=self.execute_cli(replies)
        self.assertEqual(result,2);self.assertEqual(writes.count(b'NP\0\1\x0a'),1)
        self.assertEqual(manifest['outcome'],'failure')
    def test_np_79_is_not_retried(self):
        replies=state(0x12,DATA)*2+[response(b'')]+state(2,b'\0')*2+[bytes.fromhex('000179')]
        result,writes,_=self.execute_cli(replies)
        self.assertEqual(result,2);self.assertEqual(writes.count(b'NP\0\1\x0a'),1)
    def test_unarmed_write_and_dp_rejected_before_open(self):
        link=mt.MaintenanceLink('/dev/cu.fixture',capture=mock.Mock(integration={'command':'maintenance'}))
        with mock.patch.object(link,'_open') as opened:
            with self.assertRaises(ro.ProtocolError):link.mutate('EP',b'')
            link.arm('DP',b'')
            with self.assertRaises(ro.ProtocolError):link.mutate('DP',b'')
            opened.assert_not_called()
    def test_already_detailed_does_not_write_np(self):
        class DetailedCamera(WorkflowCamera):
            def mutate(self,op,payload):
                super().mutate(op,payload)
                if op=='EP':self.mq=0x0b;self.data=b'\1'
        cam=DetailedCamera()
        with tempfile.TemporaryDirectory() as d:
            result=mt.run(cam,d,lambda *_:True,actor='user',channel='terminal')
            self.assertEqual(result['status'],'verified');self.assertEqual(cam.writes,[('EP',b'')])

    def test_short_ep_write_stops_without_retry_or_np(self):
        result,writes,manifest=self.execute_cli(state(0x12,DATA)*2,short_ep=True)
        self.assertEqual(result,2);self.assertEqual(writes.count(b'EP\0\0'),1)
        self.assertFalse(manifest['api_byte_reconstruction_complete'])
        self.assertFalse(any(x.startswith(b'NP') for x in writes))
    def test_maintenance_plan_not_accepted_as_readonly(self):
        before,after=snapshots()
        with tempfile.TemporaryDirectory() as d:
            session,port=connection.prepare(d,'maintenance-boundary',before,after,user_confirmed=True,command='maintenance')
            connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
            args=dict(orchestration_plan=session/'orchestration-plan.json',admission_report=session/'mac-admission/report.json',forwarding_gate=session/'mac-admission/utm-forwarding-gate.json',integration_session_id=session.name,serial_port=port,expected_mode='mac-client')
            self.assertTrue(binding.validate_live_binding(**args,expected_command='maintenance')['verified_before_device_open'])
            with self.assertRaises(binding.BindingError):binding.validate_live_binding(**args,expected_command='lq')
            path=session/'orchestration-plan.json';plan=json.loads(path.read_text());plan['dp_implemented']=True
            plan.pop('plan_sha256_without_this_field');plan['plan_sha256_without_this_field']=connection.gate._canonical_hash(plan);path.write_text(json.dumps(plan))
            with self.assertRaises(binding.BindingError):binding.validate_live_binding(**args,expected_command='maintenance')

    def test_empty_simple_may_report_global_one_and_final_detailed_zero(self):
        replies=state(0x12,DATA)*2+[response(b'')]+state(2,b'\1')*2+[response(b'')]+state(0x0a,b'\0')
        result,writes,manifest=self.execute_cli(replies)
        self.assertEqual(result,0);self.assertEqual(manifest['outcome'],'success')
        self.assertEqual(writes.count(b'NP\0\1\x0a'),1)
    def test_unknown_post_erase_bits_stop_without_np(self):
        for value in (0x12,0x06,0x82):
            with self.subTest(mq=value):
                result,writes,manifest=self.execute_cli(state(0x12,DATA)*2+[response(b'')]+state(value,b'\0'))
                self.assertEqual(result,2);self.assertFalse(any(x.startswith(b'NP') for x in writes))
                self.assertEqual(manifest['outcome'],'failure')
    def test_unknown_np_payload_rejected_at_transport(self):
        for value in (0x1a,0x0e,0x8a):
            link=mt.MaintenanceLink('/dev/cu.fixture',capture=mock.Mock(integration={'command':'maintenance'}))
            link._mutations=['EP'];link.arm('NP',bytes([value]))
            with mock.patch.object(link,'_open') as opened:
                with self.assertRaises(ro.ProtocolError):link.mutate('NP',bytes([value]))
                opened.assert_not_called()
    def test_nonempty_mode_mismatch_still_rejected(self):
        cam=WorkflowCamera();cam.mq=0x1a
        with self.assertRaises(ro.ProtocolError):mt.read_state(cam)
    def test_empty_global_observation_is_preserved(self):
        cam=WorkflowCamera();cam.mq=2;cam.data=b'\1'
        result=mt.describe(mt.read_state(cam))
        self.assertEqual(result['lq_global_raw'],'01');self.assertEqual(result['lq_payload_bytes'],1)
