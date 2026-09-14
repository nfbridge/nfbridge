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
import report
import f100_live_binding as binding


def snapshots():
    before=json.loads((ROOT/'mac-connection/fixtures/synthetic-before.json').read_text())
    after=json.loads((ROOT/'mac-connection/fixtures/synthetic-after.json').read_text())
    after['usb_devices'][0]['fingerprint_sha256']='a'*64
    after['serial_paths']=['/dev/cu.fixture','/dev/tty.fixture']
    return before,after


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
