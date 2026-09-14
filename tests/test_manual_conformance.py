# SPDX-License-Identifier: GPL-3.0-only
"""Manufacturer preconditions and final-frame ISO provenance regressions."""
import csv
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_maintenance import WorkflowCamera, DATA, mt, ro
from test_operation_scopes import workflow_camera, operations
from test_exports import exports, nfbridge, report
import scans


class ManualConformance(unittest.TestCase):
    def test_e_denial_or_nonboolean_never_sends_np_in_either_workflow(self):
        for answer in (False, None, 'yes', 1):
            for legacy in (True, False):
                with self.subTest(answer=answer, legacy=legacy), tempfile.TemporaryDirectory() as d:
                    cam=WorkflowCamera() if legacy else workflow_camera('record-settings','0a',empty=True)
                    def confirm(action, details):
                        return answer if action=='counter-e' else True
                    run=mt.run if legacy else operations.run
                    result=run(cam,d,confirm,actor='user',channel='terminal')
                    self.assertEqual(cam.writes,[('EP',b'')] if legacy else [])
                    self.assertEqual(result['reason'],'counter_e_not_confirmed')

    def test_e_prompt_exception_stops_without_np(self):
        for legacy in (True,False):
            with self.subTest(legacy=legacy),tempfile.TemporaryDirectory() as d:
                cam=WorkflowCamera() if legacy else workflow_camera('record-settings','0a',empty=True)
                def confirm(action,details):
                    if action=='counter-e':raise EOFError()
                    return True
                with self.assertRaises(EOFError):
                    (mt.run if legacy else operations.run)(cam,d,confirm,actor='user',channel='terminal')
                self.assertFalse(any(op=='NP' for op,_ in cam.writes))

    def test_e_is_separate_fresh_observation_and_records_relay(self):
        for legacy in (True,False):
            with self.subTest(legacy=legacy),tempfile.TemporaryDirectory() as d:
                cam=WorkflowCamera() if legacy else workflow_camera('record-settings','0a',empty=True)
                sequence=[];request=cam.request
                def record_request(op,**kw):sequence.append(op);return request(op,**kw)
                cam.request=record_request
                def confirm(action,details):sequence.append(action);return True
                result=(mt.run if legacy else operations.run)(cam,d,confirm,actor='assistant',channel='chat-relay')
                idx=sequence.index('counter-e')
                self.assertEqual(sequence[idx+1:idx+4],['MQ','OQ','LQ'])
                self.assertEqual(sequence.count('counter-e'),1)
                events=[c.kwargs for c in cam.capture.record.call_args_list if c.args[0]=='camera_counter_e_confirmation']
                self.assertEqual(len(events),1)
                self.assertEqual((events[0]['actor'],events[0]['channel']),('assistant','chat-relay'))
                self.assertIs(events[0]['confirmed'],True)
                self.assertIs(events[0]['camera_counter_read_by_app'],False)
                self.assertEqual(result['recording_effective'],'next_film_advanced_to_first_frame')

    def test_camera_changes_while_e_question_pending_blocks_np(self):
        for legacy in (True,False):
            with self.subTest(legacy=legacy),tempfile.TemporaryDirectory() as d:
                cam=WorkflowCamera() if legacy else workflow_camera('record-settings','0a',empty=True)
                def confirm(action,details):
                    if action=='counter-e':cam.data=DATA;cam.mq=3
                    return True
                with self.assertRaisesRegex(ro.ProtocolError,'empty memory'):
                    (mt.run if legacy else operations.run)(cam,d,confirm,actor='user',channel='terminal')
                self.assertFalse(any(op=='NP' for op,_ in cam.writes))

    def test_nonempty_zero_frame_container_blocks_settings(self):
        with tempfile.TemporaryDirectory() as d:
            cam=workflow_camera('record-settings','0a',empty=True)
            cam.data=bytes.fromhex('00f3000113fd')
            self.assertEqual(mt.read_state(cam)['frames'],0)
            confirm=mock.Mock(return_value=True)
            with self.assertRaisesRegex(ro.ProtocolError,'empty memory'):
                operations.run(cam,d,confirm,actor='user',channel='gui')
            confirm.assert_not_called();self.assertEqual(cam.writes,[])

    def test_each_empty_predicate_is_required(self):
        valid={'oq':0,'payload':b'\0','frames':0}
        for change in ({'oq':1},{'payload':b'\0\0'},{'frames':1}):
            with self.subTest(change=change),self.assertRaises(ro.ProtocolError):
                mt.require_empty_settings_memory(dict(valid,**change))

    def test_invalid_actor_channel_fails_before_backup_or_reads(self):
        for run in (mt.run,operations.run):
            for actor,channel in (('assistant','terminal'),('user','chat-relay'),('unknown','gui')):
                with self.subTest(run=run.__module__,actor=actor,channel=channel),tempfile.TemporaryDirectory() as d:
                    cam=mock.Mock()
                    with self.assertRaises(ro.ProtocolError):run(cam,d,mock.Mock(),actor=actor,channel=channel)
                    cam.request.assert_not_called();self.assertEqual(list(Path(d).iterdir()),[])

    def test_iso_requires_boolean_confirmation_and_unknown_stays_omitted(self):
        roll=nfbridge.demo_data()['rolls'][0]
        for answer in (None,False,'true',1,True):
            for frame in roll['frames']:
                row=dict(zip(exports.EXIF_COLUMNS,exports.exif_row(roll,frame,{'iso_unchanged_confirmed':answer})))
                self.assertEqual(row['ISO'],roll['film_speed'] if answer is True else '')
        roll=dict(roll,film_speed='0xff')
        row=dict(zip(exports.EXIF_COLUMNS,exports.exif_row(roll,roll['frames'][0],{'iso_unchanged_confirmed':True})))
        self.assertEqual(row['ISO'],'')

    def test_iso_confirmation_changes_mapping_not_source_and_is_not_sticky(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'scan.jpg').write_bytes(b'mapping-only')
            roll=nfbridge.demo_data()['rolls'][0]
            default=scans.make_mapping(d,roll)
            included=scans.make_mapping(d,roll,metadata={'iso_unchanged_confirmed':True})
            again=scans.make_mapping(d,roll)
            self.assertNotIn('EXIF:ISO',dict(default.pairs[0].tags))
            self.assertEqual(dict(included.pairs[0].tags)['EXIF:ISO'],roll['film_speed'])
            self.assertEqual(default,again)
            self.assertNotIn('iso_unchanged_confirmed',roll)

    def test_reports_label_last_iso_and_csv_default_does_not_write_it(self):
        for lang,label in (('ko','롤 마지막 감도'),('en','Last recorded ISO')):
            with self.subTest(lang=lang),tempfile.TemporaryDirectory() as d:
                path=report.save(nfbridge.demo_data(),Path(d)/'output',language=lang)
                self.assertIn(label,path.read_text())
                with (path.parent/'shooting-data.csv').open(encoding='utf-8-sig') as f:
                    self.assertIn(label,next(csv.reader(f)))
                with (path.parent/'exiftool.csv').open(encoding='utf-8-sig') as f:
                    self.assertTrue(all(row['ISO']=='' for row in csv.DictReader(f)))
                md=(path.parent/'F100_roll1.md').read_text()
                self.assertIn('status: "imported"',md)
                self.assertIn('f100_iso_source: "last_exposed_frame"',md)
                self.assertIn('rating_ei:',md)

    def test_explicit_iso_confirmation_is_per_roll_in_csv_export(self):
        with tempfile.TemporaryDirectory() as d:
            data=nfbridge.demo_data();second=dict(data['rolls'][0],roll_number=2)
            data['rolls'].append(second)
            exports.save(data,d,metadata={'1':{'iso_unchanged_confirmed':True}})
            with (Path(d)/'exiftool.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertTrue(all(row['ISO'] for row in rows[:3]))
            self.assertTrue(all(row['ISO']=='' for row in rows[3:]))
