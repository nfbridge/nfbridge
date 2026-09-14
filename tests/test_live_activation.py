# SPDX-License-Identifier: GPL-3.0-only
"""Activation boundary exercised with real validators and simulated serial only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_operation_scopes import (snapshots, connection, binding, scopes, reconnect,
                                   arguments, sealed_plan, operations, ro)
import test_operation_scopes as operation_tests
from test_maintenance import state, response, DATA, _FakeSerialModule
from test_transport_regressions import ReplyPort


class LiveActivation(unittest.TestCase):
    def session(self, folder, command='record-settings', payload='0a'):
        before,after=snapshots()
        session,port=connection.prepare(folder,'activation',before,after,user_confirmed=True)
        sealed_plan(session/'orchestration-plan.json',mac_command=command,
                    operation=scopes.descriptor(command,payload if command=='record-settings' else None),
                    np_dp_ep_implemented=True,dp_implemented=False,automatic_write_retry=False,
                    candidate_live_blocked=False,live_policy_revision=scopes.LIVE_POLICY_REVISION)
        connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
        return session,port

    def link(self, session, port, command):
        integration=binding.validate_live_binding(**arguments(session,command))
        capture=ro.CaptureSession(session/'capture',port=port,command=command,
             operation_scope=command,integration=integration,serial_config=ro.SERIAL_CONFIG)
        verified=ro._VerifiedLiveBinding(ro._VERIFIED_LIVE_BINDING_AUTHORITY,integration)
        auth=ro._issue_live_transport_authorization(port=port,capture=capture,verified_binding=verified)
        link=operations.OperationLink(port,capture=capture,live_authorization=auth,response_timeout=.03,post_frame_quiet=0)
        link.verify_before_mutation=lambda:binding.validate_live_binding(**arguments(session,command))
        return link

    def test_single_operation_entire_bound_workflow_uses_simulated_serial(self):
        for command in ('record-settings','erase-records'):
            with self.subTest(command=command),tempfile.TemporaryDirectory() as folder:
                session,port=self.session(folder,command)
                link=self.link(session,port,command)
                old=state(2,b'\0') if command=='record-settings' else state(0x12,DATA)
                new=state(0x0a,b'\1') if command=='record-settings' else state(2,b'\0')
                ser=ReplyPort(old*2+[response(b'')]+new)
                try:
                    with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                        result=operations.run(link,session/'capture',lambda *_:True,actor='user',channel='terminal')
                    self.assertEqual(result['status'],'verified')
                    writes=[x for x in ser.writes if x.startswith((b'NP',b'EP',b'DP'))]
                    self.assertEqual(writes,[b'NP\0\1\x0a'] if command=='record-settings' else [b'EP\0\0'])
                    self.assertTrue(ser.closed)
                finally:link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')
                events=[json.loads(x) for x in link.capture.events_path.read_text().splitlines()]
                self.assertTrue(events)

    def test_e_denial_after_activation_keeps_serial_writes_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            session,port=self.session(folder);link=self.link(session,port,'record-settings')
            ser=ReplyPort(state(2,b'\0'))
            try:
                with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                    result=operations.run(link,session/'capture',lambda action,_:action!='counter-e',actor='user',channel='gui')
                self.assertEqual(result['reason'],'counter_e_not_confirmed')
                self.assertFalse(any(x.startswith((b'NP',b'EP',b'DP')) for x in ser.writes))
            finally:link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_nonempty_same_mode_remains_blocked_after_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            session,port=self.session(folder,payload='02');link=self.link(session,port,'record-settings')
            ser=ReplyPort(state(3,DATA));confirm=mock.Mock(return_value=True)
            try:
                with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                    with self.assertRaisesRegex(ro.ProtocolError,'empty memory'):
                        operations.run(link,session/'capture',confirm,actor='user',channel='gui')
                confirm.assert_not_called()
                self.assertFalse(any(x.startswith(b'NP') for x in ser.writes))
            finally:link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_np_79_after_activation_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            session,port=self.session(folder);link=self.link(session,port,'record-settings')
            ser=ReplyPort(state(2,b'\0')*2+[bytes.fromhex('000179')])
            try:
                with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                    with self.assertRaisesRegex(ro.ProtocolError,'not acknowledged'):
                        operations.run(link,session/'capture',lambda *_:True,actor='assistant',channel='chat-relay')
                self.assertEqual(ser.writes.count(b'NP\0\1\x0a'),1)
            finally:link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_changed_plan_during_confirmation_fails_before_np(self):
        with tempfile.TemporaryDirectory() as folder:
            session,port=self.session(folder);link=self.link(session,port,'record-settings')
            ser=ReplyPort(state(2,b'\0')*2)
            def confirm(action,details):
                if action=='counter-e':sealed_plan(session/'orchestration-plan.json',operation=scopes.descriptor('record-settings','0b'))
                return True
            try:
                with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                    with self.assertRaises(ValueError):operations.run(link,session/'capture',confirm,actor='user',channel='gui')
                self.assertFalse(any(x.startswith(b'NP') for x in ser.writes))
            finally:link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_old_or_malformed_policy_plan_rejected_even_with_valid_self_hash(self):
        for change in ({'candidate_live_blocked':True},{'candidate_live_blocked':0},
                       {'candidate_live_blocked':None},{'live_policy_revision':'old'},{'live_policy_revision':None}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                session,_=self.session(folder)
                sealed_plan(session/'orchestration-plan.json',**change)
                with self.assertRaisesRegex(ValueError,'Live policy revision'):
                    binding.validate_live_binding(**arguments(session,'record-settings'))

    def test_issuer_rejects_old_binding_and_wrong_capture_or_port(self):
        with tempfile.TemporaryDirectory() as folder:
            session,port=self.session(folder);link=self.link(session,port,'record-settings')
            original=dict(link.capture.integration)
            try:
                for change in ({'candidate_live_blocked':True},{'candidate_live_blocked':0},
                               {'live_policy_revision':'old'},{'live_policy_revision':None}):
                    updated=dict(original,**change);link.capture.integration=updated
                    verified=ro._VerifiedLiveBinding(ro._VERIFIED_LIVE_BINDING_AUTHORITY,updated)
                    with self.assertRaises(ro.ProtocolError):
                        ro._issue_live_transport_authorization(port=port,capture=link.capture,verified_binding=verified)
                link.capture.integration=original
                verified=ro._VerifiedLiveBinding(ro._VERIFIED_LIVE_BINDING_AUTHORITY,original)
                for supplied_port,capture in (('/dev/cu.other',link.capture),(port,mock.Mock(integration={}))):
                    with self.assertRaises(ro.ProtocolError):
                        ro._issue_live_transport_authorization(port=supplied_port,capture=capture,verified_binding=verified)
            finally:link.capture.integration=original;link.capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_reconnect_read_binding_opens_only_simulated_port(self):
        with tempfile.TemporaryDirectory() as folder:
            before,after=snapshots()
            original,port=connection.prepare(folder,'original',before,after,user_confirmed=True)
            connection.final_check(original,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
            reg=Path(folder)/'registration.json'
            reconnect.register(reg,original,user_confirmed=True,actor='user',channel='gui')
            after['generated_utc']=reconnect.utc()
            session=reconnect.prepare(folder,'reconnected',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'},command='mq')
            value=binding.validate_live_binding(**arguments(session,'mq'))
            capture=ro.CaptureSession(session/'capture',port=port,command='mq',integration=value,serial_config=ro.SERIAL_CONFIG)
            verified=ro._VerifiedLiveBinding(ro._VERIFIED_LIVE_BINDING_AUTHORITY,value)
            auth=ro._issue_live_transport_authorization(port=port,capture=capture,verified_binding=verified)
            link=ro.F100Link(port,capture=capture,live_authorization=auth,response_timeout=.03,post_frame_quiet=0)
            ser=ReplyPort([response(b'\x0a')])
            try:
                with mock.patch.object(ro,'serial',_FakeSerialModule(ser)),mock.patch.object(ro.time,'sleep'):
                    self.assertEqual(link.request('MQ',expected_len=1).require_success(),b'\x0a')
                self.assertEqual(ser.writes,[b'\0',b'MQ\0\0'])
                self.assertTrue(ser.closed)
            finally:capture.finish('interrupted', 'Synthetic test cleanup; assertions establish the result')

    def test_old_reconnect_flags_rejected_even_after_hash_chain_resealed(self):
        for filename in ('report.json','utm-forwarding-gate.json'):
            for change in ({'candidate_live_blocked':True},{'candidate_live_blocked':0},
                           {'live_policy_revision':'old'}):
                with self.subTest(filename=filename,change=change),tempfile.TemporaryDirectory() as folder:
                    _,reg,after=operation_tests.ReconnectTests().setup_registration(folder)
                    session=reconnect.prepare(folder,'again',reg,after,{'generated_utc':reconnect.utc(),'status':'FAIL'},command='mq')
                    path=session/'mac-admission'/filename
                    def reseal(path,changes):
                        obj=json.loads(path.read_text());obj.update(changes);obj.pop(reconnect.HASH_FIELD)
                        obj[reconnect.HASH_FIELD]=binding._canonical_hash(obj);path.write_text(json.dumps(obj))
                    reseal(path,change)
                    if filename=='report.json':
                        reseal(path.parent/'utm-forwarding-gate.json',{'report_sha256':binding._sha256(path)})
                    with self.assertRaisesRegex(ValueError,'Reconnect (report|gate) mismatch'):
                        binding.validate_live_binding(**arguments(session,'mq'))
