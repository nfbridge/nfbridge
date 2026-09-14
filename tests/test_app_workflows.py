# SPDX-License-Identifier: GPL-3.0-only
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import library
import nfbridge
import scans


class Workflows(unittest.TestCase):
    def test_duplicate_growth_and_number_collision_preserve_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            store = library.Library(folder)
            data = nfbridge.demo_data()
            self.assertEqual(store.add(data, 'camera A')[0]['status'], 'new')
            self.assertEqual(store.add(data, 'camera A')[0]['status'], 'duplicate')
            longer = copy.deepcopy(data)
            longer['rolls'][0]['frames'].append(dict(longer['rolls'][0]['frames'][-1], frame_number=4))
            self.assertEqual(store.add(longer, 'camera A')[0]['status'], 'prefix_growth')
            changed = copy.deepcopy(data)
            changed['rolls'][0]['frames'][0]['aperture'] = '8'
            self.assertEqual(store.add(changed, 'camera A')[0]['status'], 'same_number_distinct')
            self.assertEqual(store.add(data, 'camera B')[0]['status'], 'new')
            self.assertEqual(len(store.entries()), 4)

    def test_bad_source_hash_rejected(self):
        data = nfbridge.demo_data()
        data['_source']['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                library.Library(folder).add(data, 'A')

    def test_mapping_natural_order_reverse_start_and_omissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['scan10.jpg', 'scan2.jpg', 'scan1.jpg', 'scan3.dng']:
                (root / name).write_bytes(b'example')
            (root / 'link.jpg').symlink_to(root / 'scan1.jpg')
            roll = nfbridge.demo_data()['rolls'][0]
            mapping = scans.make_mapping(root, roll)
            self.assertEqual([x.path.name for x in mapping.pairs], ['scan1.jpg', 'scan2.jpg', 'scan10.jpg'])
            self.assertEqual(set(mapping.ignored_files), {'scan3.dng', 'link.jpg'})
            mapping = scans.make_mapping(root, roll, reverse=True, start=2)
            self.assertEqual([(x.path.name, x.frame_number) for x in mapping.pairs], [('scan10.jpg', 2), ('scan2.jpg', 3)])
            self.assertEqual(mapping.unmatched_frames, (1,))
            self.assertEqual(len(mapping.unmatched_files), 1)

    def test_no_write_without_confirmation_or_after_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.jpg'
            path.write_bytes(b'old')
            mapping = scans.make_mapping(folder, nfbridge.demo_data()['rolls'][0])
            with self.assertRaises(ValueError):
                scans.write_mapping(mapping, sys.executable)
            path.write_bytes(b'new')
            with self.assertRaises(ValueError):
                scans.write_mapping(mapping, sys.executable, confirmed=True)
            self.assertFalse(Path(str(path) + '_original').exists())

    def test_existing_backup_blocks_entire_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.jpg'
            path.write_bytes(b'old')
            mapping = scans.make_mapping(folder, nfbridge.demo_data()['rolls'][0])
            Path(str(path) + '_original').write_bytes(b'precious')
            with self.assertRaises(ValueError):
                scans.write_mapping(mapping, sys.executable, confirmed=True)
            self.assertEqual(path.read_bytes(), b'old')

    def test_failed_write_stops_without_touching_original_or_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ['a.jpg', 'b.jpg']:
                (Path(folder) / name).write_bytes(b'old')
            mapping = scans.make_mapping(folder, nfbridge.demo_data()['rolls'][0])
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1, '', 'failed')
            result = scans.write_mapping(mapping, sys.executable, confirmed=True, runner=runner)
            self.assertEqual([r['status'] for r in result], ['failed', 'not_attempted'])
            self.assertEqual(len(calls), 1)
            self.assertEqual((Path(folder) / 'a.jpg').read_bytes(), b'old')
            self.assertFalse(list(Path(folder).glob('.nfbridge-*')))

    def test_staged_write_is_verified_before_original_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.jpg'
            path.write_bytes(b'original image')
            mapping = scans.make_mapping(folder, nfbridge.demo_data()['rolls'][0])
            def runner(args, **kwargs):
                stage = Path(args[-1])
                self.assertNotEqual(stage, path)
                self.assertEqual(path.read_bytes(), b'original image')
                if '-FileType' in args:
                    return subprocess.CompletedProcess(args, 0, '[{"FileType":"JPEG"}]', '')
                if '-overwrite_original' in args:
                    stage.write_bytes(b'image with metadata')
                    return subprocess.CompletedProcess(args, 0, '1 image files updated', '')
                tags = {key.split(':')[-1].rstrip('#'): value for key, value in mapping.pairs[0].tags}
                return subprocess.CompletedProcess(args, 0, json.dumps([tags]), '')
            results = scans.write_mapping(mapping, sys.executable, confirmed=True, runner=runner)
            self.assertEqual(results[0]['status'], 'verified')
            self.assertEqual(Path(str(path) + '_original').read_bytes(), b'original image')
            self.assertEqual(path.read_bytes(), b'image with metadata')

    def test_disguised_dng_never_reaches_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.jpg'
            path.write_bytes(b'DNG content')
            mapping = scans.make_mapping(folder, nfbridge.demo_data()['rolls'][0])
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, '[{"FileType":"DNG"}]', '')
            results = scans.write_mapping(mapping, sys.executable, confirmed=True, runner=runner)
            self.assertEqual(results[0]['status'], 'failed')
            self.assertEqual(len(calls), 1)
            self.assertNotIn('-overwrite_original', calls[0])
            self.assertEqual(path.read_bytes(), b'DNG content')


if __name__ == '__main__':
    unittest.main()
