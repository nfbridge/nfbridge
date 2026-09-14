# SPDX-License-Identifier: GPL-3.0-only
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import archive_check
import nfbridge

class ArchiveCheckTests(unittest.TestCase):
    def data(self):
        first=bytes.fromhex(nfbridge.demo_data()['_source']['payload_hex'])
        payload=first+b'\xf3\x00\x02'+first[4:]
        data=nfbridge.client.decode_lq(payload)
        data['_source']={'kind':'synthetic','payload_hex':payload.hex(),'sha256':hashlib.sha256(payload).hexdigest()}
        return data

    def save(self, folder, data):
        (Path(folder)/'shooting-data.json').write_text(json.dumps(data))

    def test_exact_archive_verifies_every_roll(self):
        with tempfile.TemporaryDirectory() as d:
            data=self.data();self.save(d,data)
            result=archive_check.require(d,data)
            self.assertEqual((result['verified_rolls'],result['unverified_rolls']),(2,0))
            self.assertTrue(result['payload_verified'])

    def test_missing_file_does_not_pass_even_for_empty_camera(self):
        with tempfile.TemporaryDirectory() as d:
            data=self.data();data['rolls']=[];data['roll_count']=0
            with self.assertRaises(archive_check.ArchiveIncomplete):archive_check.require(d,data)

    def test_partial_json_identifies_missing_roll_without_losing_count(self):
        with tempfile.TemporaryDirectory() as d:
            expected=self.data();saved=copy.deepcopy(expected);saved['rolls'].pop()
            self.save(d,saved);result=archive_check.inspect(d,expected)
            self.assertFalse(result['ok']);self.assertEqual(result['verified_rolls'],1)
            self.assertEqual(result['unverified_roll_numbers'],[2])

    def test_same_roll_number_different_content_is_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            expected=self.data();saved=copy.deepcopy(expected)
            saved['rolls'][0]['frames'][0]['shutter_speed']='1/8000'
            self.save(d,saved);result=archive_check.inspect(d,expected)
            self.assertEqual(result['unverified_roll_numbers'],[1])

    def test_raw_source_mismatch_fails_even_if_decoded_rows_match(self):
        with tempfile.TemporaryDirectory() as d:
            expected=self.data();saved=copy.deepcopy(expected);saved['_source']['sha256']='0'*64
            self.save(d,saved);result=archive_check.inspect(d,expected)
            self.assertEqual(result['unverified_rolls'],2)
            self.assertFalse(result['payload_verified'])

    def test_duplicate_numbers_cannot_cover_a_missing_record(self):
        with tempfile.TemporaryDirectory() as d:
            expected=self.data();saved=copy.deepcopy(expected);saved['rolls'][1]=copy.deepcopy(saved['rolls'][0])
            self.save(d,saved);result=archive_check.inspect(d,expected)
            self.assertEqual(result['unverified_roll_numbers'],[2])

    def test_symlink_and_invalid_json_are_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            data=self.data();path=Path(d)/'shooting-data.json'
            path.write_text('{bad');self.assertFalse(archive_check.inspect(d,data)['ok'])
            path.unlink();target=Path(d)/'other.json';target.write_text(json.dumps(data));path.symlink_to(target)
            self.assertFalse(archive_check.inspect(d,data)['ok'])

if __name__=='__main__':unittest.main()
