# SPDX-License-Identifier: GPL-3.0-only
"""GUI service integration: real evidence validators, synthetic snapshots/serial."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'mac-client'), str(ROOT/'mac-connection')]
import camera
import connection
from test_guided import snapshots
from test_maintenance import state, response, DATA, _FakeSerialModule
from test_transport_regressions import ReplyPort
import f100_reconnect as reconnect


def snapshots_ftdi():
    """A supported FTDI Serial-to-USB adapter (vendor family 0x0403).

    The product_id used here (0x6001, FT232R) is a real, publicly documented
    FTDI product_id used only to exercise the vendor-family match in tests.
    It is not asserted to be the exact product_id of any specific adapter
    used in physical testing (see docs/VALIDATION.md)."""
    before, after = snapshots()
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    after['usb_devices'][0].update(vendor_id='0x0403', product_id='0x6001',
                                    _name='Synthetic FTDI fixture', tree_path=['Synthetic FTDI fixture'],
                                    fingerprint_sha256='b' * 64)
    return before, after


def snapshots_prolific_other_pid():
    """A Prolific-vendor device with an untested product_id (not 2303).

    067b:2305 is a real, publicly documented Prolific product_id (another
    PL2303 variant) used only to exercise the vendor-family match. Since
    only 067b:2303 has been physically tested end to end with an F100, this
    fixture is used to prove that vendor-family eligibility alone does not
    grant use — the full admission pipeline (fingerprint, serial path,
    topology, explicit user confirmation) still gates it exactly like FTDI."""
    before, after = snapshots()
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    after['usb_devices'][0].update(vendor_id='0x067b', product_id='0x2305',
                                    _name='Synthetic Prolific-other-PID fixture',
                                    tree_path=['Synthetic Prolific-other-PID fixture'],
                                    fingerprint_sha256='e' * 64)
    return before, after


def snapshots_unsupported_chipset():
    """CH340/CH341 (WCH, vendor 0x1a86) — deliberately not in the allowlist."""
    before, after = snapshots()
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    after['usb_devices'][0].update(vendor_id='0x1a86', product_id='0x7523',
                                    _name='Synthetic unsupported chipset fixture',
                                    tree_path=['Synthetic unsupported chipset fixture'],
                                    fingerprint_sha256='c' * 64)
    return before, after


class CameraServiceTests(unittest.TestCase):
    def test_snapshot_failure_reaches_gui_with_failed_check(self):
        app = mock.Mock()
        app.run.side_effect = lambda work, done: work()
        service = camera.CameraService('/unused', backend=mock.Mock())
        before = {'snapshot_complete': False, 'parse_errors': ['disks: private path']}
        error = connection.SnapshotProblem(before, {'snapshot_complete': True})
        with self.assertRaises(connection.SnapshotProblem) as caught:
            service.launch(app, lambda prompt: (_ for _ in ()).throw(error), mock.Mock(), reading=True)
        self.assertIs(caught.exception, error)

    def test_failure_messages_distinguish_read_and_confirmed_change(self):
        app = mock.Mock()
        app.call_main.side_effect = lambda callback: callback()
        app.run.side_effect = lambda work, done: done(work())
        service = camera.CameraService('/unused', backend=mock.Mock())
        for reading, confirmed, expected in ((True, False, '가져오기를 끝내지'),
                                             (False, False, '설정이나 촬영기록은 바꾸지'),
                                             (False, True, '이미 됐을 수')):
            def action(prompt):
                if confirmed:
                    prompt('record-settings', {})
                raise OSError('test failure')
            with mock.patch.object(service, 'prompt', return_value=True):
                with self.assertRaisesRegex(ValueError, expected):
                    service.launch(app, action, mock.Mock(), reading=reading)

    def setup_backend(self, home, fixture=snapshots):
        before, after = fixture()
        calls = []
        def snapshot():
            obj = copy.deepcopy(before if not calls else after)
            calls.append(True)
            obj['generated_utc'] = reconnect.utc()
            return obj
        backend = camera.CameraBackend(home, snapshot=snapshot,
            network=lambda: {'generated_utc': reconnect.utc(), 'status': 'FAIL'}, platform='darwin')
        return backend, calls

    def invoke(self, backend, replies, *, choice='0a', deny=None, action='settings', hook=None):
        seen = []
        def prompt(name, details):
            seen.append((name, details))
            if hook:
                hook(name, details)
            if name == 'choose-settings':
                return choice
            return name != deny
        ser = ReplyPort(replies)
        with mock.patch.object(camera.ro, 'serial', _FakeSerialModule(ser)), mock.patch.object(camera.ro.time, 'sleep'):
            result = getattr(backend, action)(prompt)
        return result, ser, seen

    def test_first_import_and_reconnect_preserve_data_and_need_no_new_disconnection(self):
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d)
            result, ser, seen = self.invoke(backend, state(0x12, DATA), action='read')
            self.assertEqual([x[0] for x in seen], ['disconnect','usb-only','review-cable','connect-camera'])
            self.assertEqual(result['data']['roll_count'], 1)
            self.assertEqual(result['data']['_source']['sha256'], hashlib.sha256(DATA).hexdigest())
            session = Path(result['session'])
            self.assertTrue((session/'shooting-data.json').exists())
            camera.nfbridge.verify_capture(session/'mac-client/capture')
            self.assertEqual(ser.writes, [b'\0',b'MQ\0\0',b'\0',b'OQ\0\0',b'\0',b'LQ\0\0'])
            original = backend.registration.read_bytes()
            result2, ser2, seen2 = self.invoke(backend, state(0x12, DATA), action='read')
            self.assertEqual([x[0] for x in seen2], ['connect-camera'])
            self.assertNotEqual(result2['session'], result['session'])
            self.assertEqual(backend.registration.read_bytes(), original)

    def test_all_six_setting_values_get_exactly_one_np_and_gui_e_confirmation(self):
        for value in camera.SETTING_LABELS:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as d:
                backend, _ = self.setup_backend(d)
                old = 3 if value == '02' else 2
                result, ser, seen = self.invoke(backend, [response(bytes([old]))] + state(old,b'\0')*2 + [response(b'')] + state(int(value,16),b'\0'), choice=value)
                self.assertEqual(result['status'],'verified')
                self.assertEqual([x for x in ser.writes if x.startswith((b'NP',b'EP',b'DP'))], [b'NP\0\1'+bytes.fromhex(value)])
                self.assertLess([x[0] for x in seen].index('record-settings'), [x[0] for x in seen].index('counter-e'))
                events = [json.loads(x) for x in (Path(result['session'])/'mac-client/capture/events.jsonl').read_text().splitlines()]
                e = next(x for x in events if x.get('event')=='camera_counter_e_confirmation')
                self.assertEqual((e['actor'], e['channel'], e['camera_counter_read_by_app']), ('user','gui',False))

    def test_erase_saves_viewable_archive_before_confirmation_and_never_changes_mode(self):
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self.setup_backend(d)
            def hook(action, details):
                if action == 'erase-records':
                    archived = Path(details['archive'])
                    self.assertTrue((archived/'index.html').exists())
                    self.assertEqual(json.loads((archived/'shooting-data.json').read_text())['_source']['payload_hex'], DATA.hex())
            result, ser, seen = self.invoke(backend, [response(b'\x12')] + state(0x12,DATA)*2 + [response(b'')] + state(2,b'\0'), choice='erase',hook=hook)
            self.assertEqual(result['status'],'verified')
            self.assertNotIn('counter-e',[x[0] for x in seen])
            self.assertEqual([x for x in ser.writes if x.startswith((b'NP',b'EP',b'DP'))],[b'EP\0\0'])

    def test_cancel_and_e_denial_never_write(self):
        for deny in ('record-settings','counter-e'):
            with self.subTest(deny=deny), tempfile.TemporaryDirectory() as d:
                backend, _ = self.setup_backend(d)
                result, ser, _ = self.invoke(backend, [response(b'\2')]+state(2,b'\0'), deny=deny)
                self.assertEqual(result['status'],'cancelled')
                self.assertFalse(any(x.startswith((b'NP',b'EP',b'DP')) for x in ser.writes))

    def test_failed_archive_blocks_erase_before_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self.setup_backend(d)
            seen=[]
            with mock.patch.object(camera.report, 'save', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError,'disk full'):
                    self.invoke(backend, [response(b'\x12')]+state(0x12,DATA), choice='erase',hook=lambda action,details:seen.append(action))
            self.assertNotIn('erase-records',seen)
            manifests = list(Path(d).glob('sessions/*/mac-client/capture/session-manifest.json'))
            self.assertIn('failure',[json.loads(p.read_text())['outcome'] for p in manifests])

    def test_nonempty_settings_rejected_without_any_write(self):
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self.setup_backend(d)
            with self.assertRaises(camera.ro.ProtocolError):
                self.invoke(backend,[response(b'\x12')]+state(0x12,DATA))
            for p in Path(d).glob('sessions/*/mac-client/capture/host-to-camera.bin'):
                self.assertNotIn(b'NP',p.read_bytes())

    def test_np_uncertain_ack_is_not_retried_and_failure_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self.setup_backend(d)
            with self.assertRaisesRegex(camera.ro.ProtocolError,'not acknowledged'):
                self.invoke(backend,[response(b'\2')]+state(2,b'\0')*2+[bytes.fromhex('000179')])
            raw=b''.join(p.read_bytes() for p in Path(d).glob('sessions/*/mac-client/capture/host-to-camera.bin'))
            self.assertEqual(raw.count(b'NP\0\1\x0a'),1)

    def test_declined_enrollment_does_not_collect_or_open(self):
        with tempfile.TemporaryDirectory() as d:
            backend,calls=self.setup_backend(d)
            with self.assertRaises(camera.Cancelled):
                self.invoke(backend,[],deny='disconnect',action='read')
            self.assertEqual(calls,[])
            self.assertFalse(backend.registration.exists())

    def test_ftdi_adapter_completes_enrollment_like_prolific(self):
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d, fixture=snapshots_ftdi)
            result, ser, seen = self.invoke(backend, state(0x12, DATA), action='read')
            self.assertEqual([x[0] for x in seen], ['disconnect', 'usb-only', 'review-cable', 'connect-camera'])
            self.assertEqual(result['data']['roll_count'], 1)
            self.assertTrue(backend.registration.exists())

    def test_unsupported_chipset_is_rejected_before_admission_session_created(self):
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d, fixture=snapshots_unsupported_chipset)
            with self.assertRaisesRegex(ValueError, '지원되는 USB-serial 어댑터'):
                self.invoke(backend, [], action='read')
            self.assertFalse(backend.registration.exists())
            self.assertEqual(list(Path(d).glob('sessions/*')), [])

    def test_ftdi_without_review_cable_confirmation_is_cancelled(self):
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d, fixture=snapshots_ftdi)
            with self.assertRaises(camera.Cancelled):
                self.invoke(backend, [], deny='review-cable', action='read')
            self.assertFalse(backend.registration.exists())
            self.assertEqual(list(Path(d).glob('sessions/*')), [])

    def test_ftdi_with_ambiguous_serial_paths_fails_before_port_open(self):
        with tempfile.TemporaryDirectory() as d:
            before, after = snapshots_ftdi()
            after['serial_paths'] = ['/dev/cu.fixture', '/dev/cu.fixture-2']
            backend, calls = self.setup_backend(d, fixture=lambda: (before, after))
            fake = mock.Mock()
            with mock.patch.object(camera.ro, 'serial', fake):
                with self.assertRaisesRegex(connection.ConnectionProblem, '케이블 이외의 장치 변화'):
                    backend.read(lambda *_: True)
                fake.Serial.assert_not_called()
            self.assertFalse(backend.registration.exists())

    def test_ftdi_with_unrelated_usb_device_also_changing_fails(self):
        with tempfile.TemporaryDirectory() as d:
            before, after = snapshots_ftdi()
            after['usb_devices'] = after['usb_devices'] + [{
                '_name': 'Unrelated synthetic device', 'vendor_id': '0x05ac', 'product_id': '0x1234',
                'tree_path': ['Unrelated synthetic device'], 'fingerprint_sha256': 'd' * 64,
            }]
            backend, calls = self.setup_backend(d, fixture=lambda: (before, after))
            fake = mock.Mock()
            with mock.patch.object(camera.ro, 'serial', fake):
                with self.assertRaises(connection.ConnectionProblem):
                    backend.read(lambda *_: True)
                fake.Serial.assert_not_called()
            self.assertFalse(backend.registration.exists())

    def test_prolific_other_product_id_completes_enrollment_like_exact_pair(self):
        # Proves vendor-family eligibility for Prolific behaves like FTDI:
        # a PID other than the one physically tested (2303) is still
        # eligible to enter admission and, when the rest of the evidence is
        # clean, completes the same as the exact pair.
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d, fixture=snapshots_prolific_other_pid)
            result, ser, seen = self.invoke(backend, state(0x12, DATA), action='read')
            self.assertEqual([x[0] for x in seen], ['disconnect', 'usb-only', 'review-cable', 'connect-camera'])
            self.assertEqual(result['data']['roll_count'], 1)
            self.assertTrue(backend.registration.exists())

    def test_prolific_other_product_id_without_review_cable_confirmation_is_cancelled(self):
        with tempfile.TemporaryDirectory() as d:
            backend, calls = self.setup_backend(d, fixture=snapshots_prolific_other_pid)
            with self.assertRaises(camera.Cancelled):
                self.invoke(backend, [], deny='review-cable', action='read')
            self.assertFalse(backend.registration.exists())
            self.assertEqual(list(Path(d).glob('sessions/*')), [])

    def test_prolific_other_product_id_with_ambiguous_serial_paths_fails_before_port_open(self):
        with tempfile.TemporaryDirectory() as d:
            before, after = snapshots_prolific_other_pid()
            after['serial_paths'] = ['/dev/cu.fixture', '/dev/cu.fixture-2']
            backend, calls = self.setup_backend(d, fixture=lambda: (before, after))
            fake = mock.Mock()
            with mock.patch.object(camera.ro, 'serial', fake):
                with self.assertRaisesRegex(connection.ConnectionProblem, '케이블 이외의 장치 변화'):
                    backend.read(lambda *_: True)
                fake.Serial.assert_not_called()
            self.assertFalse(backend.registration.exists())

    def test_prolific_other_product_id_with_unrelated_usb_device_also_changing_fails(self):
        with tempfile.TemporaryDirectory() as d:
            before, after = snapshots_prolific_other_pid()
            after['usb_devices'] = after['usb_devices'] + [{
                '_name': 'Unrelated synthetic device', 'vendor_id': '0x05ac', 'product_id': '0x1234',
                'tree_path': ['Unrelated synthetic device'], 'fingerprint_sha256': 'f' * 64,
            }]
            backend, calls = self.setup_backend(d, fixture=lambda: (before, after))
            fake = mock.Mock()
            with mock.patch.object(camera.ro, 'serial', fake):
                with self.assertRaises(connection.ConnectionProblem):
                    backend.read(lambda *_: True)
                fake.Serial.assert_not_called()
            self.assertFalse(backend.registration.exists())

    def test_prolific_other_product_id_reconnect_with_changed_topology_fails_before_port_open(self):
        # A device that passed admission once must still fail on reconnect
        # if the topology it is bound to changes, regardless of vendor.
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self.setup_backend(d, fixture=snapshots_prolific_other_pid)
            self.invoke(backend, state(2, b'\0'), action='read')
            original = backend.snapshot
            def changed():
                snap = original(); snap['disk_identifiers'].append('disk99'); return snap
            backend.snapshot = changed
            fake = mock.Mock()
            with mock.patch.object(camera.ro, 'serial', fake):
                with self.assertRaisesRegex(ValueError, 'topology changed'):
                    backend.read(lambda *_: True)
                fake.Serial.assert_not_called()

    def test_changed_reconnect_topology_fails_before_port_open(self):
        with tempfile.TemporaryDirectory() as d:
            backend,_=self.setup_backend(d)
            self.invoke(backend,state(2,b'\0'),action='read')
            original=backend.snapshot
            def changed():
                snap=original();snap['disk_identifiers'].append('disk99');return snap
            backend.snapshot=changed
            fake=mock.Mock()
            with mock.patch.object(camera.ro,'serial',fake):
                with self.assertRaisesRegex(ValueError,'topology changed'):
                    backend.read(lambda *_:True)
                fake.Serial.assert_not_called()

    def test_invalid_settings_choice_does_not_create_write_plan(self):
        with tempfile.TemporaryDirectory() as d:
            backend,_=self.setup_backend(d)
            with self.assertRaisesRegex(ValueError,'지원하지'):
                self.invoke(backend,[response(b'\2')],choice='00')
            for p in Path(d).glob('sessions/*/orchestration-plan.json'):
                self.assertEqual(json.loads(p.read_text())['mac_command'] in ('lq','mq'),True)

    def test_erase_dialog_reports_verified_rolls_and_checks_again_before_ep(self):
        with tempfile.TemporaryDirectory() as d:
            backend,_=self.setup_backend(d)
            def hook(action, details):
                if action=='erase-records':
                    self.assertEqual((details['verified_rolls'],details['total_rolls'],details['unverified_rolls']),(1,1,0))
            result,ser,_=self.invoke(backend,[response(b'\x12')]+state(0x12,DATA)*2+[response(b'')]+state(2,b'\0'),choice='erase',hook=hook)
            events=[json.loads(line) for line in (Path(result['session'])/'mac-client/capture/events.jsonl').read_text().splitlines()]
            names=[event['event'] for event in events]
            self.assertLess(names.index('viewable_archive_verified'),names.index('operation_confirmation'))
            self.assertLess(names.index('archive_rechecked_before_erase'),names.index('operation_write_intent'))

    def test_changed_archive_while_confirming_blocks_ep(self):
        for change in ('delete','wrong-roll-content'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                backend,_=self.setup_backend(d)
                def hook(action,details):
                    if action=='erase-records':
                        path=Path(details['archive'])/'shooting-data.json'
                        if change=='delete':path.unlink()
                        else:
                            data=json.loads(path.read_text());data['rolls'][0]['frames'].pop()
                            path.write_text(json.dumps(data))
                with self.assertRaises(camera.archive_check.ArchiveIncomplete):
                    self.invoke(backend,[response(b'\x12')]+state(0x12,DATA)*2,choice='erase',hook=hook)
                for path in Path(d).glob('sessions/*/mac-client/capture/host-to-camera.bin'):
                    self.assertNotIn(b'EP',path.read_bytes())

    def test_partial_report_save_never_reaches_erase_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            backend,_=self.setup_backend(d);save=camera.report.save;seen=[]
            def partial(*args,**kwargs):
                page=save(*args,**kwargs);path=page.parent/'shooting-data.json'
                data=json.loads(path.read_text());data['rolls']=[];data['roll_count']=0
                path.write_text(json.dumps(data));return page
            with mock.patch.object(camera.report,'save',side_effect=partial):
                with self.assertRaises(camera.archive_check.ArchiveIncomplete) as error:
                    self.invoke(backend,[response(b'\x12')]+state(0x12,DATA),choice='erase',hook=lambda name,_:seen.append(name))
            self.assertEqual(error.exception.report['unverified_rolls'],1)
            self.assertNotIn('erase-records',seen)
            for path in Path(d).glob('sessions/*/mac-client/capture/host-to-camera.bin'):
                self.assertNotIn(b'EP',path.read_bytes())

if __name__ == '__main__': unittest.main()
