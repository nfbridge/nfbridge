# SPDX-License-Identifier: GPL-3.0-only
import argparse
import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import nfbridge as app
import connection
from i18n import Translator
import report
import f100_live_binding as binding


def snapshots():
    before=json.loads((ROOT/'mac-connection/fixtures/synthetic-before.json').read_text())
    after=json.loads((ROOT/'mac-connection/fixtures/synthetic-after.json').read_text())
    after['usb_devices'][0]['fingerprint_sha256']='a'*64
    after['serial_paths']=['/dev/cu.fixture','/dev/tty.fixture']
    after['usb_devices'][0]['serial_client_registry_ids']=[101]
    after['serial_bsd_clients']=[{'registry_entry_id':101,'callout_device':'/dev/cu.fixture','dialin_device':'/dev/tty.fixture'}]
    return before,after


class SupportedAdapterTests(unittest.TestCase):
    def test_prolific_physically_tested_pair_is_supported(self):
        self.assertTrue(connection.is_supported_adapter('0x067b', '0x2303'))

    def test_prolific_vendor_family_is_supported_regardless_of_product_id(self):
        # Prolific is allowlisted at the vendor-family level, the same policy
        # as FTDI: this eligibility check is not the security boundary, and
        # a candidate with an untested product_id must still pass the full
        # admission pipeline (fingerprint, serial path, topology, explicit
        # user confirmation) to actually be used — see
        # CameraServiceTests.test_prolific_other_product_id_* in
        # tests/test_camera_service.py for that proof at the app layer.
        for product_id in ('0x2305', '0x23a3', '0x0000', '0x9999'):
            with self.subTest(product_id=product_id):
                self.assertTrue(connection.is_supported_adapter('0x067b', product_id))

    def test_ftdi_vendor_family_is_supported_regardless_of_product_id(self):
        for product_id in ('0x6001', '0x6015', '0x0000', '0xffff'):
            with self.subTest(product_id=product_id):
                self.assertTrue(connection.is_supported_adapter('0x0403', product_id))

    def test_case_insensitive_matching(self):
        self.assertTrue(connection.is_supported_adapter('0X067B', '0X2303'))
        self.assertTrue(connection.is_supported_adapter('0X0403', '0X6001'))

    def test_other_chipsets_remain_unsupported(self):
        for vendor_id, product_id in (('0x1a86', '0x7523'),   # CH340/CH341
                                       ('0x10c4', '0xea60'),   # CP2102/CP210x
                                       ('0x0000', '0x0000')):
            with self.subTest(vendor_id=vendor_id, product_id=product_id):
                self.assertFalse(connection.is_supported_adapter(vendor_id, product_id))


class ConnectionGuidanceOrderTests(unittest.TestCase):
    def test_cli_usb_first_connect_guidance_orders_macos_allow_before_continuing(self):
        source = (ROOT / 'app/nfbridge.py').read_text()
        start = source.index('케이블/어댑터의 USB 쪽을 Mac에 연결하세요.')
        end = source.index("'", start)
        text = source[start:end]
        self.assertLess(text.index('먼저 허용'), text.index('확인한 다음에만'))
        self.assertIn('카메라 쪽은 아직 연결하지 마세요', text)

    def test_cli_camera_power_on_guidance_orders_power_on_before_continuing(self):
        source = (ROOT / 'app/nfbridge.py').read_text()
        start = source.index('F100의 전원이 꺼진 상태에서')
        end = source.index("'", start)
        text = source[start:end]
        self.assertLess(text.index('케이블을 연결하세요'), text.index('F100의 전원을 켜세요'))
        self.assertLess(text.index('F100의 전원을 켜세요'), text.index('켜진 것을 확인한 다음에만'))


class GuidedTests(unittest.TestCase):
    def test_demo_subprocess_needs_no_serial_or_private_files(self):
        with tempfile.TemporaryDirectory() as d:
            result=subprocess.run([sys.executable,str(ROOT/'app/nfbridge.py'),'--demo','--no-open','--output',d],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            pages=list(Path(d).glob('demo-*/index.html'));self.assertEqual(len(pages),1)
            text=pages[0].read_text();self.assertIn('예제 데이터',text);self.assertIn('1/400',text)
            self.assertNotIn('<script src=',text)
            data=json.loads(pages[0].with_name('shooting-data.json').read_text())
            self.assertEqual(data['rolls'][0]['film_speed'],'400')
            self.assertEqual(data['rolls'][0]['frame_count'],3)
            with pages[0].with_name('shooting-data.csv').open(encoding='utf-8-sig') as f:self.assertEqual(len(list(csv.reader(f))),4)

    def test_no_approval_means_no_session(self):
        before,after=snapshots()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(connection.ConnectionProblem):connection.prepare(d,'denied',before,after)
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_full_wizard_evidence_chain_reaches_existing_verifier(self):
        before,after=snapshots()
        with tempfile.TemporaryDirectory() as d:
            session,port=connection.prepare(d,'wizard-test',before,after,user_confirmed=True)
            connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL','violations':['online test fixture']})
            gate=json.loads((session/'mac-admission/utm-forwarding-gate.json').read_text())
            self.assertEqual(gate['network_gate_status'],'EXEMPT_USER_REVIEWED_CABLE')
            result=binding.validate_live_binding(orchestration_plan=session/'orchestration-plan.json',admission_report=session/'mac-admission/report.json',forwarding_gate=session/'mac-admission/utm-forwarding-gate.json',integration_session_id=session.name,serial_port=port,expected_mode='mac-client',expected_command='lq')
            self.assertTrue(result['verified_before_device_open'])
            plan=json.loads((session/'orchestration-plan.json').read_text())
            self.assertIn('lq --experimental-live',plan['commands']['mac_client_preview_only'])

    def test_complete_fake_camera_read_and_report(self):
        import contextlib
        import io
        import f100_readonly as client
        from test_transport_regressions import ReplyPort
        from test_f100_capture_session import _FakeSerialModule
        before,after=snapshots()
        with tempfile.TemporaryDirectory() as d:
            session,port=connection.prepare(d,'fake-camera',before,after,user_confirmed=True)
            connection.final_check(session,port,snapshot_collector=lambda:after,network_collector=lambda:{'status':'FAIL'})
            payload=client._read_lq_fixture(ROOT/'mac-client/fixtures/golden/detailed_two_rolls.hex')
            raw=(len(payload)+1).to_bytes(2,'big')+b'\x61'+payload
            fake=ReplyPort([bytes.fromhex('000179'),bytes.fromhex('0002611a'),bytes.fromhex('0003610020'),raw])
            argv=['nfbridge','--port',port,'--capture-dir',str(session/'mac-client/capture'),'--integration-session-id',session.name,'--orchestration-plan',str(session/'orchestration-plan.json'),'--admission-report',str(session/'mac-admission/report.json'),'--utm-forwarding-gate',str(session/'mac-admission/utm-forwarding-gate.json'),'--post-frame-quiet','0','lq','--experimental-live']
            output=io.StringIO()
            with mock.patch.object(sys,'argv',argv),mock.patch.object(client,'serial',_FakeSerialModule(fake)),mock.patch.object(client.time,'sleep'),contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(client.main(),0)
            app.verify_capture(session/'mac-client/capture')
            data=json.loads(output.getvalue())
            page=report.save(data,session/'report')
            self.assertTrue(page.exists())
            self.assertEqual(fake.writes,[b'\0',b'MQ\0\0',b'\0',b'MQ\0\0',b'\0',b'OQ\0\0',b'\0',b'LQ\0\0'])
            result=connection.orchestrator.inspect_session(session)
            self.assertEqual(result['status'],'PASS',result['errors'])

    def test_extra_device_or_missing_serial_stops(self):
        before,after=snapshots()
        for field,new in [('serial_paths',[]),('usb_devices',after['usb_devices']*2),('snapshot_complete',False)]:
            changed=copy.deepcopy(after);changed[field]=new
            with self.subTest(field=field),self.assertRaises(connection.ConnectionProblem):connection.inspect(before,changed)

    def test_incomplete_snapshot_names_failed_check_without_private_details(self):
        before,after=snapshots()
        for snapshot in (before,after):
            snapshot['snapshot_complete']=False
            snapshot['parse_errors']=['disks: ValueError: SECRET_DEVICE_NAME']
            snapshot['commands']={'disks':{'ok':True,'exit_code':0,'stderr':''}}
        with self.assertRaises(connection.SnapshotProblem) as caught:
            connection.inspect(before,after)
        error=caught.exception
        self.assertIn('연결 전: 디스크 목록',str(error))
        self.assertIn('연결 후: 디스크 목록',str(error))
        self.assertNotIn('SECRET_DEVICE_NAME',str(error))
        with tempfile.TemporaryDirectory() as folder:
            translator=Translator(folder)
            translator.language='en'
            self.assertIn('disk list',translator.error(error))
            self.assertNotIn('private-volume-name',translator.error(error))

    def test_incomplete_snapshot_reports_command_and_exit_status(self):
        before,after=snapshots()
        after['snapshot_complete']=False
        after['parse_errors']=['disks: command failed']
        after['commands']={'disks':{'ok':False,'exit_code':2,'stderr':'sensitive serial'}}
        with self.assertRaises(connection.SnapshotProblem) as caught:
            connection.inspect(before,after)
        self.assertIn('디스크 목록 — 명령 실행 실패 (종료 코드 2)',str(caught.exception))
        self.assertNotIn('sensitive serial',str(caught.exception))

    def test_report_escapes_text_and_never_overwrites(self):
        data=app.demo_data();data['rolls'][0]['frames'][0]['shutter_speed']='<script>alert(1)</script>'
        data['rolls'][0]['frames'][0]['aperture']='=HYPERLINK("bad")'
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'report';page=report.save(data,target)
            self.assertIn('&lt;script&gt;',page.read_text());self.assertNotIn('<script>alert',page.read_text())
            self.assertIn("'=HYPERLINK",(target/'shooting-data.csv').read_text(encoding='utf-8-sig'))
            with self.assertRaises(FileExistsError):report.save(data,target)

    def test_read_failure_is_not_success_and_logs_are_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            def runner(cmd,**kwargs):
                self.assertEqual(cmd[-2:],['lq','--experimental-live'])
                self.assertNotIn('shell',kwargs)
                return subprocess.CompletedProcess(cmd,2,'','timeout')
            with self.assertRaisesRegex(ValueError,'읽지 못했습니다'):app.read_camera(path,'/dev/cu.fixture',runner)
            self.assertEqual((path/'read-diagnostics.txt').read_text(),'timeout')

    def test_cancel_choice_defaults_to_no(self):
        for value in ['', 'n', 'anything']:
            self.assertFalse(app.ask('confirm',lambda _:value))

if __name__=='__main__':unittest.main()
