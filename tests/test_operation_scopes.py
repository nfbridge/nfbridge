# SPDX-License-Identifier: GPL-3.0-only
import argparse
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from test_guided import snapshots, connection, binding
from test_maintenance import WorkflowCamera, DATA
import f100_operation_scope as scopes
import f100_reconnect as reconnect
import f100_record_operations as operations
import f100_readonly as ro
from test_transport_regressions import ReplyPort


def arguments(session, command):
    return dict(orchestration_plan=session/'orchestration-plan.json',
                admission_report=session/'mac-admission/report.json',
                forwarding_gate=session/'mac-admission/utm-forwarding-gate.json',
                integration_session_id=session.name, serial_port='/dev/cu.fixture',
                expected_mode='mac-client', expected_command=command)


def sealed_plan(path, **changes):
    value=json.loads(path.read_text());value.update(changes)
    value.pop('plan_sha256_without_this_field', None)
    value['plan_sha256_without_this_field']=binding._canonical_hash(value)
    path.write_text(json.dumps(value))


def workflow_camera(scope, value=None, *, empty=False):
    cam=WorkflowCamera()
    if empty:cam.mq=2;cam.data=b'\0'
    op=scopes.descriptor(scope,value)
    cam.capture.command=scope;cam.capture.operation_scope=scope
    cam.capture.integration={'command':scope,'operation_scope':scope,'operation':op}
    original=cam.mutate
    def mutate(opcode,payload):
        if opcode=='NP':cam.writes.append((opcode,payload));cam.mq=(cam.mq&~0x0b)|payload[0]
        else:original(opcode,payload)
    cam.mutate=mutate
    return cam


class OperationScopeTests(unittest.TestCase):
    def test_all_six_values_bound_to_plan_capture_and_verifier(self):
        for payload in sorted(scopes.NP_VALUES):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as d:
                before,after=snapshots()
                session,port=connection.prepare(d,'scope-test',before,after,user_confirmed=True)
                op=scopes.descriptor('record-settings',payload)
                sealed_plan(session/'orchestration-plan.json',mac_command='record-settings',operation=op,
                            np_dp_ep_implemented=True,dp_implemented=False,automatic_write_retry=False,
                            candidate_live_blocked=False,live_policy_revision=scopes.LIVE_POLICY_REVISION)
                connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
                result=binding.validate_live_binding(**arguments(session,'record-settings'))
                self.assertEqual(result['operation'],op)
                capture=ro.CaptureSession(session/'capture',port=port,command='record-settings',
                                          operation_scope='record-settings',integration=result,serial_config=ro.SERIAL_CONFIG)
                verified=ro._VerifiedLiveBinding(ro._VERIFIED_LIVE_BINDING_AUTHORITY,result)
                auth=ro._issue_live_transport_authorization(port=port,capture=capture,verified_binding=verified)
                self.assertEqual(auth.port,port)
                capture.finish('success')
                self.assertEqual(json.loads(capture.manifest_path.read_text())['operation_scope'],'record-settings')
                with self.assertRaises(ValueError):binding.validate_live_binding(**arguments(session,'erase-records'))

    def test_250_nonallowlisted_bytes_and_lengths_rejected(self):
        for raw in range(256):
            if f'{raw:02x}' not in scopes.NP_VALUES:
                with self.subTest(raw=raw),self.assertRaises(ValueError):scopes.descriptor('record-settings',f'{raw:02x}')
        for payload in ('','0001','0A',None,True,1):
            with self.subTest(payload=payload),self.assertRaises(ValueError):scopes.descriptor('record-settings',payload)

    def test_wrong_opcode_payload_type_and_attempt_count_rejected(self):
        for change in ({'opcode':'NP'},{'opcode':'DP'},{'payload_hex':'03'},{'maximum_write_attempts':2},
                       {'maximum_write_attempts':True},{'automatic_write_retry':0},{'extra':True}):
            op=scopes.descriptor('erase-records');op.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):scopes.validate(op,'erase-records')

    def test_new_orchestrator_plan_and_invalid_value_leaves_no_session(self):
        with tempfile.TemporaryDirectory() as d:
            for command,value in [('record-settings','0a'),('erase-records',None)]:
                args=argparse.Namespace(root=Path(d),session_id=command,mode='mac-client',program=None,
                     guest_com=None,serial_port='/dev/cu.fixture',vm_pty=None,mac_command=command,record_value=value)
                path=connection.orchestrator.create_plan(args)
                plan=json.loads(path.read_text())
                self.assertEqual(plan['operation'],scopes.descriptor(command,value))
                self.assertIn('API ONLY',plan['commands']['mac_client_preview_only'])
                self.assertIs(plan['candidate_live_blocked'],False)
                self.assertEqual(plan['live_policy_revision'],scopes.LIVE_POLICY_REVISION)
            args.session_id='bad';args.mac_command='record-settings';args.record_value='ff'
            with self.assertRaises(ValueError):connection.orchestrator.create_plan(args)
            self.assertFalse((Path(d)/'bad').exists())

    def test_mismatched_capture_scope_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ro.CaptureSession(Path(d)/'capture',port='/dev/cu.fixture',command='erase-records',
                    operation_scope='record-settings',integration={},serial_config=ro.SERIAL_CONFIG)
            self.assertFalse((Path(d)/'capture').exists())

    def test_settings_empty_mode_switch_and_each_allowed_target(self):
        for target in sorted(scopes.NP_VALUES):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as d:
                cam=workflow_camera('record-settings',target,empty=True)
                result=operations.run(cam,d,lambda *_:True,actor='user',channel='gui')
                self.assertEqual(result['status'],'unchanged' if target=='02' else 'verified')
                self.assertEqual(cam.writes,[] if target=='02' else [('NP',bytes.fromhex(target))])
                self.assertFalse(any(op=='EP' for op,_ in cam.writes))

    def test_nonempty_mode_change_refused_before_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            cam=workflow_camera('record-settings','0a');cam.mq=3;confirm=mock.Mock(return_value=True)
            with self.assertRaisesRegex(ro.ProtocolError,'Settings require empty memory'):
                operations.run(cam,d,confirm,actor='user',channel='gui')
            confirm.assert_not_called();self.assertEqual(cam.writes,[])

    def test_nonempty_same_mode_settings_refused_before_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            cam=workflow_camera('record-settings','02');cam.mq=3
            confirm=mock.Mock(return_value=True)
            with self.assertRaisesRegex(ro.ProtocolError,'Settings require empty memory'):
                operations.run(cam,d,confirm,actor='user',channel='gui')
            confirm.assert_not_called();self.assertEqual(cam.data,DATA)
            self.assertEqual(cam.mq,3);self.assertEqual(cam.writes,[])

    def test_erase_backup_and_actor_channel_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            cam=workflow_camera('erase-records')
            def confirm(action,details):
                self.assertEqual((Path(d)/'backup-lq.bin').read_bytes(),DATA)
                self.assertEqual(action,'erase-records');self.assertEqual(len(details['backup_sha256']),64)
                return True
            result=operations.run(cam,d,confirm,actor='assistant',channel='chat-relay')
            self.assertEqual(result['status'],'verified');self.assertEqual(cam.writes,[('EP',b'')])
            events=[c for c in cam.capture.record.call_args_list if c.args[0]=='operation_confirmation']
            self.assertEqual(events[0].kwargs['actor'],'assistant');self.assertEqual(events[0].kwargs['channel'],'chat-relay')

    def test_cancel_backup_change_camera_change_and_wrong_confirmation_stop(self):
        for case in ('cancel','backup','camera','string'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as d:
                cam=workflow_camera('erase-records')
                def confirm(*_):
                    if case=='backup':(Path(d)/'backup-lq.bin').write_bytes(b'changed')
                    if case=='camera':cam.data=b'\0';cam.mq=3
                    return False if case=='cancel' else 'yes' if case=='string' else True
                if case in ('cancel','string'):
                    self.assertEqual(operations.run(cam,d,confirm,actor='user',channel='gui')['status'],'cancelled')
                else:
                    with self.assertRaises(ro.ProtocolError):operations.run(cam,d,confirm,actor='user',channel='gui')
                self.assertEqual(cam.writes,[])

    def test_failed_postwrite_checks_do_not_retry(self):
        for scope,value in [('erase-records',None),('record-settings','0a')]:
            with self.subTest(scope=scope),tempfile.TemporaryDirectory() as d:
                cam=workflow_camera(scope,value,empty=scope=='record-settings')
                cam.mutate=lambda op,payload:cam.writes.append((op,payload)) # ACK without effect
                with self.assertRaises(ro.ProtocolError):operations.run(cam,d,lambda *_:True,actor='user',channel='gui')
                self.assertEqual(len(cam.writes),1)

    def transport(self,scope,value=None):
        op=scopes.descriptor(scope,value)
        capture=mock.Mock(command=scope,operation_scope=scope,
                          integration={'command':scope,'operation_scope':scope,'operation':op})
        link=operations.OperationLink('/dev/cu.fixture',capture=capture)
        link.verify_before_mutation=lambda:dict(capture.integration)
        return link

    def test_mismatched_operation_never_opens_port(self):
        for op,payload in [('EP',b''),('DP',b''),('NP',b'\x0b'),('NP',b'\x0a\x00')]:
            link=self.transport('record-settings','0a');link.arm(op,payload)
            with mock.patch.object(link,'_open') as opened:
                with self.assertRaises(ValueError):link.mutate(op,payload)
                opened.assert_not_called()

    def test_write_79_short_write_and_exception_are_consumed_without_retry(self):
        for case in ('79','short','exception','success'):
            with self.subTest(case=case):
                link=self.transport('erase-records');link.arm('EP',b'')
                ser=ReplyPort([bytes.fromhex('000179' if case=='79' else '000161')])
                if case=='short':ser.write=mock.Mock(return_value=0)
                if case=='exception':ser.write=mock.Mock(side_effect=OSError('uncertain transfer'))
                with mock.patch.object(link,'_open',return_value=contextlib.nullcontext(ser)) as opened, mock.patch.object(ro.time,'sleep'):
                    if case=='success':link.mutate('EP',b'')
                    else:
                        with self.assertRaises((ValueError,OSError)):link.mutate('EP',b'')
                    link.arm('EP',b'')
                    with self.assertRaises(ro.ProtocolError):link.mutate('EP',b'')
                    self.assertEqual(opened.call_count,1)

    def test_six_np_frames_and_79_never_repeat(self):
        for payload in sorted(scopes.NP_VALUES):
            for status in ('61', '79'):
                with self.subTest(payload=payload,status=status):
                    link=self.transport('record-settings',payload)
                    data=bytes.fromhex(payload);link.arm('NP',data)
                    ser=ReplyPort([bytes.fromhex('0001'+status)])
                    with mock.patch.object(link,'_open',return_value=contextlib.nullcontext(ser)),mock.patch.object(ro.time,'sleep'):
                        if status=='61':link.mutate('NP',data)
                        else:
                            with self.assertRaises(ro.ProtocolError):link.mutate('NP',data)
                        link.arm('NP',data)
                        with self.assertRaises(ro.ProtocolError):link.mutate('NP',data)
                    self.assertEqual(ser.writes,[b'\0',b'NP\0\1'+data])

    def test_unknown_mq_bits_prevent_np(self):
        for value in (0x06,0x12,0x22,0x82):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as d:
                cam=workflow_camera('record-settings','0a',empty=True);cam.mq=value
                with self.assertRaisesRegex(ro.ProtocolError,'Unknown MQ bits'):
                    operations.run(cam,d,lambda *_:True,actor='user',channel='gui')
                self.assertEqual(cam.writes,[])

    def test_changed_binding_prevents_write(self):
        link=self.transport('erase-records');link.arm('EP',b'')
        link.verify_before_mutation=lambda:{}
        with mock.patch.object(link,'_open') as opened:
            with self.assertRaises(ro.ProtocolError):link.mutate('EP',b'')
            opened.assert_not_called()


class ReconnectTests(unittest.TestCase):
    def setup_registration(self,d):
        before,after=snapshots()
        session,port=connection.prepare(d,'original',before,after,user_confirmed=True)
        connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
        regpath=Path(d)/'registration.json'
        reconnect.register(regpath,session,user_confirmed=True,actor='user',channel='gui')
        after['generated_utc']=reconnect.utc()
        return session,regpath,after

    def test_matching_reconnect_is_distinct_and_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            original,reg,after=self.setup_registration(d)
            baseline=reconnect.source_files(original)
            session=reconnect.prepare(d,'reconnected',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'},
                                      command='record-settings',record_value='0a')
            result=binding.validate_live_binding(**arguments(session,'record-settings'))
            self.assertEqual(result['operation'],scopes.descriptor('record-settings','0a'))
            self.assertIs(result['candidate_live_blocked'],False)
            self.assertEqual(result['live_policy_revision'],scopes.LIVE_POLICY_REVISION)
            self.assertEqual(baseline,reconnect.source_files(original))
            report=json.loads((session/'mac-admission/report.json').read_text())
            self.assertEqual(report['camera_connection_state'],'not_asserted')
            self.assertFalse((session/'mac-admission/approval.json').exists())
            with self.assertRaises(ValueError):binding.validate_live_binding(**arguments(session,'erase-records'))

    def test_different_fingerprint_topology_vid_pid_and_port_rejected(self):
        for change in ('fingerprint','topology','vid','pid','port','extra_hid','incomplete'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                _,reg,after=self.setup_registration(d)
                if change=='fingerprint':after['usb_devices'][0]['fingerprint_sha256']='b'*64
                if change=='topology':after['usb_devices'][0]['tree_path']=['another hub','cable']
                if change=='vid':after['usb_devices'][0]['vendor_id']='1234'
                if change=='pid':after['usb_devices'][0]['product_id']='1234'
                if change=='port':after['serial_paths']=['/dev/cu.other']
                if change=='extra_hid':after['hid_devices'].append({'name':'unreviewed keyboard'})
                if change=='incomplete':after['snapshot_complete']=False
                with self.assertRaises(ValueError):reconnect.prepare(d,'reconnect',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'})
                self.assertFalse((Path(d)/'reconnect').exists())

    def test_corrupt_initial_evidence_rejected_even_if_file_resealed(self):
        for reseal in (False,True):
            with self.subTest(reseal=reseal),tempfile.TemporaryDirectory() as d:
                original,reg,after=self.setup_registration(d)
                path=original/'mac-admission/after.json';data=json.loads(path.read_text())
                data['usb_devices'][0]['fingerprint_sha256']='b'*64
                if reseal:data=connection.sealed(data)
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError,'Original inspection evidence changed'):
                    reconnect.prepare(d,'reconnect',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'})

    def test_expired_and_future_current_snapshot_rejected(self):
        for delta in (-901,120):
            with self.subTest(delta=delta),tempfile.TemporaryDirectory() as d:
                _,reg,after=self.setup_registration(d)
                after['generated_utc']=(datetime.now(timezone.utc)+timedelta(seconds=delta)).isoformat()
                with self.assertRaises(ValueError):reconnect.prepare(d,'reconnect',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'})

    def test_binding_expiry_after_plan_generation_is_rechecked(self):
        with tempfile.TemporaryDirectory() as d:
            _,reg,after=self.setup_registration(d)
            session=reconnect.prepare(d,'reconnect',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'})
            with self.assertRaisesRegex(ValueError,'stale'):
                binding.validate_live_binding(**arguments(session,'lq'),now=datetime.now(timezone.utc)+timedelta(seconds=901))

    def test_plan_mutation_resealed_still_breaks_report_chain(self):
        with tempfile.TemporaryDirectory() as d:
            _,reg,after=self.setup_registration(d)
            session=reconnect.prepare(d,'reconnect',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'},command='record-settings',record_value='0a')
            sealed_plan(session/'orchestration-plan.json',operation=scopes.descriptor('record-settings','0b'))
            with self.assertRaises(ValueError):binding.validate_live_binding(**arguments(session,'record-settings'))

    def test_no_registration_confirmation_means_no_registration_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):reconnect.register(Path(d)/'reg.json',d,user_confirmed=False,actor='user',channel='gui')
            self.assertFalse((Path(d)/'reg.json').exists())


if __name__=='__main__':unittest.main()
