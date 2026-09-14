# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic regression tests; no private diagnostic dump or hardware access."""
import copy
import plistlib
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mac-connection'))
import f100_usb_admission as admission


def sample():
    return {
        'AllDisks': ['disk0', 'disk0s1', 'disk1', 'disk1s1', 'disk1s1s1'],
        'WholeDisks': ['disk0', 'disk1'],
        'VolumesFromDisks': ['Macintosh HD', 'Macintosh HD'],
        'AllDisksAndPartitions': [
            {'DeviceIdentifier': 'disk0', 'Partitions': [
                {'DeviceIdentifier': 'disk0s1'}]},
            {'DeviceIdentifier': 'disk1',
             'APFSPhysicalStores': [{'DeviceIdentifier': 'disk0s1'}],
             'APFSVolumes': [
                 {'DeviceIdentifier': 'disk1s1', 'VolumeName': 'Macintosh HD'},
                 {'DeviceIdentifier': 'disk1s1s1', 'VolumeName': 'Macintosh HD'}]},
        ],
    }


class DiskVolumeNameTests(unittest.TestCase):
    def assert_rejected(self, data):
        with self.assertRaises(ValueError):
            admission._normalize_disks(plistlib.dumps(data))

    def test_duplicate_display_names_xml_accepted(self):
        data = sample()
        self.assertEqual(admission._normalize_disks(plistlib.dumps(data)), sorted(data['AllDisks']))

    def test_duplicate_display_names_binary_accepted(self):
        data = sample()
        self.assertEqual(admission._normalize_disks(plistlib.dumps(data, fmt=plistlib.FMT_BINARY)), sorted(data['AllDisks']))

    def test_unique_display_names_accepted(self):
        data = sample(); data['VolumesFromDisks'] = ['Alpha', 'Beta']
        self.assertEqual(admission._normalize_disks(plistlib.dumps(data)), sorted(data['AllDisks']))

    def test_empty_display_name_list_accepted(self):
        data = sample(); data['VolumesFromDisks'] = []
        self.assertEqual(admission._normalize_disks(plistlib.dumps(data)), sorted(data['AllDisks']))

    def test_missing_display_name_list_accepted(self):
        data = sample(); del data['VolumesFromDisks']
        self.assertEqual(admission._normalize_disks(plistlib.dumps(data)), sorted(data['AllDisks']))

    def test_display_name_list_must_be_list(self):
        data = sample(); data['VolumesFromDisks'] = 'Macintosh HD'
        self.assert_rejected(data)

    def test_display_name_must_be_string(self):
        data = sample(); data['VolumesFromDisks'] = ['Macintosh HD', 7]
        self.assert_rejected(data)

    def test_display_name_empty_rejected_under_existing_policy(self):
        data = sample(); data['VolumesFromDisks'] = ['']
        self.assert_rejected(data)

    def test_duplicate_all_disks_rejected(self):
        data = sample(); data['AllDisks'].append('disk0')
        self.assert_rejected(data)

    def test_duplicate_whole_disks_rejected(self):
        data = sample(); data['WholeDisks'].append('disk0')
        self.assert_rejected(data)

    def test_unknown_whole_disk_rejected(self):
        data = sample(); data['WholeDisks'].append('disk999')
        self.assert_rejected(data)

    def test_duplicate_hierarchy_identifier_rejected(self):
        data = sample(); data['AllDisksAndPartitions'].append(copy.deepcopy(data['AllDisksAndPartitions'][0]))
        self.assert_rejected(data)

    def test_missing_hierarchy_identifier_rejected(self):
        data = sample(); data['AllDisksAndPartitions'][1]['APFSVolumes'].pop()
        self.assert_rejected(data)

    def test_duplicate_physical_store_rejected(self):
        data = sample(); data['AllDisksAndPartitions'][1]['APFSPhysicalStores'].append({'DeviceIdentifier': 'disk0s1'})
        self.assert_rejected(data)

    def test_unknown_physical_store_rejected(self):
        data = sample(); data['AllDisksAndPartitions'][1]['APFSPhysicalStores'] = [{'DeviceIdentifier': 'disk999'}]
        self.assert_rejected(data)

    def test_duplicate_plist_key_still_rejected(self):
        payload = plistlib.dumps(sample())
        original = b'<key>VolumesFromDisks</key>'
        replacement = b'<key>VolumesFromDisks</key><array/><key>VolumesFromDisks</key>'
        self.assertEqual(payload.count(original), 1)
        with self.assertRaises(ValueError):
            admission._normalize_disks(payload.replace(original, replacement))


if __name__ == '__main__':
    unittest.main()
