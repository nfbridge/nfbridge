#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline parity-reference and golden-fixture tests."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import f100_readonly as m


FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "golden"


class TestReferenceCompare(unittest.TestCase):
    def _compare_pair(self, stem):
        reference = m.load_parity_reference(GOLDEN / f"{stem}.reference.json")
        payload = m._read_lq_fixture(str(GOLDEN / f"{stem}.hex"))
        decoded = m.decode_lq(payload, table_dir=GOLDEN, table_policy="raw")
        return m.compare_lq_reference(reference, decoded)

    def _write_reference(self, directory, source, expected=None):
        path = Path(directory) / "reference.json"
        path.write_text(
            json.dumps(
                {
                    "schema": m.PARITY_REFERENCE_SCHEMA,
                    "source": source,
                    "expected": expected or {"mode": "simple"},
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_simple_golden_reference_matches(self):
        report = self._compare_pair("simple_one_roll")
        self.assertEqual(report["overall"], "MATCH")
        self.assertEqual(report["summary"]["differ"], 0)

    def test_detailed_two_rolls_golden_reference_matches(self):
        report = self._compare_pair("detailed_two_rolls")
        self.assertEqual(report["overall"], "MATCH")
        self.assertGreater(report["summary"]["match"], 40)

    def test_empty_roll_golden_reference_matches(self):
        report = self._compare_pair("empty_roll")
        self.assertEqual(report["overall"], "MATCH")

    def test_difference_reports_json_path(self):
        reference = m.load_parity_reference(
            GOLDEN / "simple_one_roll.reference.json"
        )
        reference["expected"]["rolls"][0]["frame_count"] = 2
        payload = m._read_lq_fixture(str(GOLDEN / "simple_one_roll.hex"))
        decoded = m.decode_lq(payload, table_dir=GOLDEN, table_policy="raw")
        report = m.compare_lq_reference(reference, decoded)
        self.assertEqual(report["overall"], "DIFFER")
        differences = {
            item["path"] for item in report["comparisons"]
            if item["status"] == "DIFFER"
        }
        self.assertIn("$.rolls[0].frame_count", differences)

    def test_null_reference_field_is_unknown(self):
        reference = m.load_parity_reference(
            GOLDEN / "simple_one_roll.reference.json"
        )
        reference["expected"]["mode"] = None
        payload = m._read_lq_fixture(str(GOLDEN / "simple_one_roll.hex"))
        decoded = m.decode_lq(payload, table_dir=GOLDEN, table_policy="raw")
        report = m.compare_lq_reference(reference, decoded)
        self.assertEqual(report["overall"], "UNKNOWN")
        self.assertEqual(report["summary"]["unknown"], 1)

    def test_reference_role_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_reference(
                directory,
                {
                    "application": "nikon_photo_secretary_ii",
                    "reference_role": "independent_cross_check",
                    "evidence_kind": "application_export",
                    "hardware_validated": False,
                },
            )
            with self.assertRaisesRegex(m.ProtocolError, "manufacturer_reference"):
                m.load_parity_reference(path)

    def test_photo_secretary_manufacturer_role_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_reference(
                directory,
                {
                    "application": "nikon_photo_secretary_ii",
                    "reference_role": "manufacturer_reference",
                    "evidence_kind": "application_export",
                    "hardware_validated": False,
                },
            )
            reference = m.load_parity_reference(path)
            self.assertEqual(
                reference["source"]["reference_role"], "manufacturer_reference"
            )

    def test_synthetic_reference_cannot_claim_hardware_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_reference(
                directory,
                {
                    "application": "synthetic",
                    "reference_role": "synthetic_golden",
                    "evidence_kind": "synthetic",
                    "hardware_validated": True,
                },
            )
            with self.assertRaisesRegex(m.ProtocolError, "cannot be hardware-validated"):
                m.load_parity_reference(path)

    def test_hardware_validated_application_requires_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            source = {
                "application": "nikon_photo_secretary_ii",
                "reference_role": "manufacturer_reference",
                "evidence_kind": "wire_capture_transcription",
                "hardware_validated": True,
            }
            path = self._write_reference(
                directory,
                source,
            )
            with self.assertRaisesRegex(m.ProtocolError, "require provenance"):
                m.load_parity_reference(path)

            valid_provenance = {
                "run_id": "schema-test-only",
                "captured_at_utc": "2026-08-29T00:00:00Z",
                "application_version": "schema-test-only",
                "approval_scope": "schema-test-only",
                "camera_state": "schema-test-only",
                "raw_capture_sha256": "a" * 64,
                "raw_capture_size_bytes": 1,
            }
            invalid_cases = (
                ("non-UTC timestamp", {"captured_at_utc": "2026-08-29T09:00:00+09:00"}, "must use UTC"),
                ("uppercase hash", {"raw_capture_sha256": "A" * 64}, "lowercase hex"),
                ("zero size", {"raw_capture_size_bytes": 0}, "positive integer"),
            )
            for label, replacement, message in invalid_cases:
                with self.subTest(label=label):
                    invalid_source = dict(source)
                    invalid_source["provenance"] = dict(valid_provenance)
                    invalid_source["provenance"].update(replacement)
                    path = self._write_reference(directory, invalid_source)
                    with self.assertRaisesRegex(m.ProtocolError, message):
                        m.load_parity_reference(path)

    def test_complete_hardware_provenance_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_reference(
                directory,
                {
                    "application": "nikon_photo_secretary_ii",
                    "reference_role": "manufacturer_reference",
                    "evidence_kind": "wire_capture_transcription",
                    "hardware_validated": True,
                    "provenance": {
                        "run_id": "schema-test-only",
                        "captured_at_utc": "2026-08-29T00:00:00Z",
                        "application_version": "schema-test-only",
                        "approval_scope": "schema-test-only",
                        "camera_state": "schema-test-only",
                        "raw_capture_sha256": "a" * 64,
                        "raw_capture_size_bytes": 1,
                    },
                },
            )
            reference = m.load_parity_reference(path)
            self.assertTrue(reference["source"]["hardware_validated"])

    def test_raw_codes_survive_display_table_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "lq_shutter_speed_table.tsv"
            with table.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, delimiter="\t")
                writer.writerow(["raw_hex", "raw_decimal", "display"])
                writer.writerow(["0xfd", "253", '1.5"'])
            payload = m._read_lq_fixture(str(GOLDEN / "simple_one_roll.hex"))
            decoded = m.decode_lq(
                payload, table_dir=Path(directory), table_policy="raw"
            )
            frame = decoded["rolls"][0]["frames"][0]
            self.assertEqual(frame["shutter_speed_raw"], "0xfd")
            self.assertEqual(frame["shutter_speed"], '1.5"')

    def test_negative_truncated_fixture_is_rejected(self):
        payload = m._read_lq_fixture(
            str(FIXTURES / "negative" / "truncated_roll.hex")
        )
        with self.assertRaises(m.ProtocolError):
            m.decode_lq(payload, table_dir=GOLDEN, table_policy="raw")

    def test_compare_cli_is_offline_and_capture_free(self):
        argv = [
            "f100_readonly.py",
            "compare",
            "--reference",
            str(GOLDEN / "simple_one_roll.reference.json"),
            "--capture",
            str(GOLDEN / "simple_one_roll.hex"),
        ]
        with mock.patch.object(m.sys, "argv", argv), mock.patch(
            "sys.stdout"
        ), mock.patch.object(m, "CaptureSession") as capture_session:
            self.assertEqual(m.main(), 0)
        capture_session.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
