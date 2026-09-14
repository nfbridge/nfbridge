# SPDX-License-Identifier: GPL-3.0-only
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
import nfbridge,report,exports
WHEN=datetime(2026,9,13,21,40,tzinfo=timezone.utc)
class ExportTests(unittest.TestCase):
    def test_selected_formats_only_create_requested_user_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'output'
            result=report.save(nfbridge.demo_data(),root,imported=WHEN,formats={'html','json'})
            self.assertEqual(result.name,'index.html')
            self.assertTrue((root/'index.html').exists())
            self.assertTrue((root/'shooting-data.json').exists())
            self.assertFalse((root/'shooting-data.csv').exists())
            self.assertFalse((root/'exiftool.csv').exists())
            self.assertFalse((root/'F100_roll1.md').exists())
            page=(root/'index.html').read_text()
            self.assertIn('shooting-data.json',page)
            self.assertNotIn('exiftool.csv',page)

    def test_five_outputs_template_and_source_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            data=nfbridge.demo_data();root=Path(d)/'output'
            report.save(data,root,demo=True,imported=WHEN)
            self.assertTrue(all((root/name).exists() for name in ['index.html','shooting-data.csv','shooting-data.json','exiftool.csv','F100_roll1.md']))
            text=(root/'F100_roll1.md').read_text()
            self.assertIn('"imported"',text);self.assertIn('f100_date_source: "imported"',text)
            self.assertIn('강한 컷 3:',text);self.assertIn('판단/의도',text)
            self.assertIn('1/400',text);self.assertIn('BULB',text)
            source=json.loads((root/'shooting-data.json').read_text())['_source']
            self.assertEqual(hashlib.sha256(bytes.fromhex(source['payload_hex'])).hexdigest(),source['sha256'])
    def test_user_metadata_yaml_safety_and_filename(self):
        with tempfile.TemporaryDirectory() as d:
            data=nfbridge.demo_data();root=Path(d)
            exports.save(data,root,metadata={'1':{'date':'2026-09-12','order':'9th','film_code':'TEST','film':'Film: |\n# heading'}},imported=WHEN,sections=True)
            text=(root/'260912_F100_9th_TEST.md').read_text()
            self.assertIn('f100_date_source: "user"',text);self.assertIn('### 컷 3',text)
            self.assertIn('film: "Film: |\\n# heading"',text)
    def test_simple_keeps_flash_and_me_but_missing_details_blank(self):
        roll={'roll_number':44,'film_speed':'400','frames':[{'frame_number':1,'shutter_speed':'1/500','aperture':'4.5','focal_length':'34','flash_type':'ttl','multiple_exposure':True}]}
        meta=exports.roll_metadata(roll,{},WHEN)
        text=exports.markdown(roll,'simple',meta,WHEN)
        self.assertIn('TTL · 다중노출',text);self.assertIn('| - | - | - |',text)
        self.assertIn('lenses: []',text)
    def test_exif_dates_and_unknowns_not_invented(self):
        data=nfbridge.demo_data();roll=data['rolls'][0]
        row=dict(zip(exports.EXIF_COLUMNS,exports.exif_row(roll,roll['frames'][2],{'date':'2026-09-13'})))
        self.assertEqual(row['ExposureTime'],'');self.assertEqual(row['DateTimeOriginal'],'');self.assertEqual(row['SourceFile'],'')
        frame=dict(roll['frames'][0],flash_type='ttl')
        row=dict(zip(exports.EXIF_COLUMNS,exports.exif_row(roll,frame,{'datetime_original':'2026-09-13 14:05:06'})))
        self.assertEqual(row['DateTimeOriginal'],'2026:09:13 14:05:06');self.assertEqual(row['Flash#'],'')
        self.assertEqual(row['ExposureProgram#'],4);self.assertEqual(row['MeteringMode#'],5)
    def test_vault_existing_notes_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);vault=root/'vault';vault.mkdir();(vault/'F100_roll1.md').write_text('MY NOTES')
            output=root/'output';output.mkdir()
            result=exports.save(nfbridge.demo_data(),output,imported=WHEN,vault=vault)
            self.assertEqual((vault/'F100_roll1.md').read_text(),'MY NOTES')
            self.assertEqual(result['vault'][0]['status'],'existing_not_overwritten')
    def test_path_traversal_rejected(self):
        roll=nfbridge.demo_data()['rolls'][0]
        for name in ['../escape','/absolute','..']:
            with self.assertRaises(ValueError):exports.roll_metadata(roll,{'roll_id':name},WHEN)
    def test_csv_mapping_is_explicit_and_all_frame_fields_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'output';report.save(nfbridge.demo_data(),root,imported=WHEN)
            with (root/'exiftool.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            mapping=json.loads((root/'exiftool-row-map.json').read_text())
            self.assertEqual(len(rows),3);self.assertEqual(mapping[2]['frame'],3)
            self.assertTrue(all(row['SourceFile']=='' for row in rows))
            with (root/'shooting-data.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertIn('mode_flags_raw',json.loads(rows[0]['전체 원시·해석 필드 JSON']))
