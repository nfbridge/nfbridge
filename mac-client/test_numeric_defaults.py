# SPDX-License-Identifier: GPL-3.0-only
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import f100_numeric as n
import f100_readonly as m

class TestNumericDefaults(unittest.TestCase):
    def test_observed_anchors(self):
        for kind, code, label in [('shutter',0x34,'1/400'),('shutter',0x36,'1/500'),('shutter',0xe1,'BULB'),('shutter',0xe2,'30"'),('aperture',0x16,'3.5'),('aperture',0x19,'4.2'),('aperture',0x38,'25'),('aperture',0x64,'F--'),('focal_length',0x3c,'28'),('focal_length',0x4b,'44'),('iso',1,'6'),('iso',17,'250'),('iso',19,'400')]:
            with self.subTest(kind=kind, code=code):self.assertEqual(n.display(kind,code),(label,'camera_observed'))

    def test_ev_signed_boundaries_and_zero(self):
        for code,label in [(0,'0.0'),(4,'+0.7'),(0xf4,'-2.0'),(0x80,'-21.3'),(0x7f,'+21.2')]:
            self.assertEqual(n.display('ev',code)[0],label)

    def test_unobserved_gap_and_estimates(self):
        for code in [0x4f,0x70,0x71,0xe0]:self.assertEqual(n.display('shutter',code),(f'0x{code:02x}','unknown'))
        self.assertEqual(n.display('focal_length',0xff)[1],'unknown')
        self.assertEqual(n.display('shutter',1)[1],'formula_estimate')
        self.assertEqual(n.display('focal_length',61)[1],'formula_estimate')
        self.assertEqual(n.display('iso',0)[1],'unknown')

    def test_default_without_tables_and_raw_opt_out(self):
        data=b'\x01\xf3\x00\x01'+bytes([1,0x34,0x16,0x3c,0,0x3c,0x6a,0x16,0x1a,0,4,0,4])+b'\x13\xfd'
        with tempfile.TemporaryDirectory() as d:
            result=m.decode_lq(data,table_dir=Path(d))
            frame=result['rolls'][0]['frames'][0]
            self.assertEqual((frame['shutter_speed'],frame['aperture'],frame['focal_length']),('1/400','3.5','28'))
            self.assertEqual(result['rolls'][0]['film_speed'],'400')
            self.assertEqual(frame['shutter_speed_raw'],'0x34')
            self.assertEqual(m.decode_lq(data,table_dir=Path(d),table_policy='raw')['rolls'][0]['frames'][0]['shutter_speed'],'0x34')
            with self.assertRaises(FileNotFoundError):m.decode_lq(data,table_dir=Path(d),table_policy='strict')
            (Path(d)/'lq_shutter_speed_table.tsv').write_text('raw_hex\traw_decimal\tdisplay\n0x34\t52\tcustom\n')
            result=m.decode_lq(data,table_dir=Path(d))
            self.assertEqual(result['rolls'][0]['frames'][0]['shutter_speed'],'custom')
            self.assertEqual(result['_value_tables']['sources_by_code']['shutter']['0x34'],'external_table')

    def test_all_byte_inputs_are_total(self):
        for kind in ['shutter','aperture','focal_length','ev','iso']:
            for code in range(256):
                label,source=n.display(kind,code)
                self.assertIsInstance(label,str)
                self.assertIsInstance(source,str)
