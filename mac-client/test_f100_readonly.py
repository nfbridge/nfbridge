#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Regression tests for f100_readonly.py.

These tests preserve the parser, table-loader, and transport regressions found
during private development without bundling internal audit artifacts:

  - P0: 0xFD is a *valid* shutter raw code (lq_shutter_speed_table.tsv:
    0xFD -> 1.5") and must not be misread as the roll trailer when it
    appears inside a frame record.
  - P1: the TSV loader must read the display column (index 2), not
    raw_decimal (index 1), and must handle CSV-style quoting.
  - P1: the shutter table's real filename is lq_shutter_speed_table.tsv,
    not lq_shutter_table.tsv.
  - Transport-layer edges: oversized/undersized response length caps,
    arbitrary read splits, multiple frames per feed(), decoder reset.

Run: python3 -m unittest test_f100_readonly -v
"""

import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import f100_readonly as m


def _authorized_link(port="/dev/cu.fixture", **kwargs):
    integration = {
        "binding_schema": "f100-live-evidence-binding/0.2",
        "session_id": "fixture-p3-001",
        "serial_port": port,
        "verified_before_device_open": True,
    }
    capture = mock.Mock()
    capture.integration = dict(integration)
    verified = m._VerifiedLiveBinding(
        authority=m._VERIFIED_LIVE_BINDING_AUTHORITY,
        integration=dict(integration),
    )
    authorization = m._issue_live_transport_authorization(
        port=port, capture=capture, verified_binding=verified
    )
    return m.F100Link(
        port, capture=capture, live_authorization=authorization, **kwargs
    )


# ---------------------------------------------------------------------------
# decode_cq / decode_mq / decode_oq — baseline sanity (unchanged by the audit)
# ---------------------------------------------------------------------------

class TestBaselineDecoders(unittest.TestCase):
    def test_decode_cq_known_bits(self):
        cq = m.decode_cq(bytes([0x01, 0x00, 0x00, 0x80]))
        self.assertFalse(cq["CSM01"]["value"])
        self.assertTrue(cq["CSM17"]["value"])

    def test_decode_cq_wrong_length_raises(self):
        with self.assertRaises(m.ProtocolError):
            m.decode_cq(bytes([0x01, 0x00, 0x00]))

    def test_decode_mq_known_value(self):
        mq = m.decode_mq(bytes([0x1B]))
        self.assertEqual(mq["memory_full_action"], "delete_old_data")
        self.assertTrue(mq["record_shooting_data"])
        self.assertEqual(mq["recording_mode"], "detailed")

    def test_decode_oq_is_not_frame_count(self):
        oq = m.decode_oq(bytes([0x00, 0x05]))
        self.assertEqual(oq["value_be16"], 5)
        self.assertIn("NOT the frame count", oq["_note"])


# ---------------------------------------------------------------------------
# encode_request / ResponseDecoder
# ---------------------------------------------------------------------------

class TestProtocolCodec(unittest.TestCase):
    def test_encode_request_has_no_attention_byte(self):
        self.assertEqual(m.encode_request("CQ", b""), b"CQ\x00\x00")

    def test_encode_request_keeps_payloadless_lq_available_offline(self):
        self.assertEqual(m.encode_request("LQ"), b"LQ\x00\x00")

    def test_encode_request_rejects_np_dp_ep_and_unknown_opcodes(self):
        for opcode in ("NP", "DP", "EP", "ZZ"):
            with self.subTest(opcode=opcode):
                with self.assertRaisesRegex(m.ProtocolError, "read-only allowlist"):
                    m.encode_request(opcode)

    def test_encode_request_rejects_payloads_for_allowed_opcodes(self):
        for opcode in ("CQ", "MQ", "OQ", "LQ"):
            with self.subTest(opcode=opcode):
                with self.assertRaisesRegex(m.ProtocolError, "must not contain a payload"):
                    m.encode_request(opcode, b"\x01")

    def test_encoder_rejects_str_and_bytes_subclasses(self):
        class Opcode(str):
            def encode(self, *_args, **_kwargs):
                return b"NP"

        class Payload(bytes):
            pass

        with self.assertRaises(m.ProtocolError):
            m.encode_request(Opcode("CQ"))
        with self.assertRaises(m.ProtocolError):
            m.encode_request("CQ", Payload())

    def test_decoder_basic_frame(self):
        data = bytes([0x01, 0x00, 0x00, 0x80])
        frame = (1 + len(data)).to_bytes(2, "big") + bytes([0x61]) + data
        dec = m.ResponseDecoder()
        frames = dec.feed(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].status, 0x61)
        self.assertEqual(frames[0].data, data)

    def test_decoder_arbitrary_split_points(self):
        data = bytes(range(20))
        frame = (1 + len(data)).to_bytes(2, "big") + bytes([0x61]) + data
        for split in range(1, len(frame)):
            with self.subTest(split=split):
                dec = m.ResponseDecoder()
                first = dec.feed(frame[:split])
                self.assertEqual(first, [])
                second = dec.feed(frame[split:])
                self.assertEqual(len(second), 1)
                self.assertEqual(second[0].data, data)

    def test_decoder_multiple_frames_in_one_feed(self):
        data_a, data_b = b"\x01\x02", b"\x03\x04\x05"
        frame_a = (1 + len(data_a)).to_bytes(2, "big") + bytes([0x61]) + data_a
        frame_b = (1 + len(data_b)).to_bytes(2, "big") + bytes([0x61]) + data_b
        dec = m.ResponseDecoder()
        frames = dec.feed(frame_a + frame_b)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].data, data_a)
        self.assertEqual(frames[1].data, data_b)

    def test_decoder_respects_configurable_max_length(self):
        data = bytes(600)
        frame = (1 + len(data)).to_bytes(2, "big") + bytes([0x61]) + data
        with self.assertRaises(m.ProtocolError):
            m.ResponseDecoder(maximum_length=512).feed(frame)
        frames = m.ResponseDecoder(maximum_length=2000).feed(frame)
        self.assertEqual(len(frames), 1)
        self.assertEqual(len(frames[0].data), 600)

    def test_decoder_reset_returns_and_clears_buffer(self):
        dec = m.ResponseDecoder()
        dec.feed(bytes([0x00, 0x05, 0x61, 0x01]))  # partial frame, header says 5
        dropped = dec.reset()
        self.assertEqual(dropped, bytes([0x00, 0x05, 0x61, 0x01]))
        self.assertEqual(dec.buffered, b"")


# ---------------------------------------------------------------------------
# decode_lq — P0: 0xFD as a legitimate shutter code, not a false trailer
# ---------------------------------------------------------------------------

class TestLqTrailerDetection(unittest.TestCase):
    def test_0xFD_in_every_simple_record_position_preserves_structure(self):
        base = [1, 0x3C, 8, 0x32, 0]
        for position in range(5):
            with self.subTest(position=position):
                rec = base.copy()
                rec[position] = 0xFD
                payload = (
                    bytes([0x00])
                    + bytes.fromhex("F30001")
                    + bytes(rec)
                    + bytes([0x0D, 0xFD])
                )
                result = m.decode_lq(payload, table_policy="raw")
                self.assertEqual(result["rolls"][0]["frame_count"], 1)

    def test_0xFD_in_every_detailed_record_position_preserves_structure(self):
        base = [1, 0x3C, 8, 0x32, 0, 0x32, 0x32, 8, 8, 0, 0, 0, 0]
        for position in range(13):
            with self.subTest(position=position):
                rec = base.copy()
                rec[position] = 0xFD
                payload = (
                    bytes([0x01])
                    + bytes.fromhex("F30001")
                    + bytes(rec)
                    + bytes([0x0D, 0xFD])
                )
                result = m.decode_lq(payload, table_policy="raw")
                self.assertEqual(result["rolls"][0]["frame_count"], 1)

    def test_counterexample_0xFD_shutter_in_simple_record(self):
        # 00 F3 00 01 01 FD 00 00 00 0D FD
        # ^^ mode/roll   ^ frame record   ^ ISO trailer/end
        # frame: frame_number=01, shutter=FD (valid: 1.5"), aperture=00,
        # focal=00, flash/multi=00 ; roll trailer=0D, then final FD.
        payload = bytes.fromhex("00 F3 00 01 01 FD 00 00 00 0D FD".replace(" ", ""))
        result = m.decode_lq(payload, table_policy="raw")
        self.assertEqual(result["roll_count"], 1)
        roll = result["rolls"][0]
        self.assertEqual(roll["film_speed_raw"], "0x0d")
        self.assertEqual(len(roll["frames"]), 1)
        frame = roll["frames"][0]
        self.assertEqual(frame["frame_number"], 1)
        # No TSV present in this test's cwd -> raw hex fallback.
        self.assertEqual(frame["shutter_speed"], "0xfd")

    def test_0xFD_shutter_in_detailed_record(self):
        # detailed record (13 bytes): frame_number, shutter=FD, aperture,
        # focal, flash/multi, then 8 more bytes that must NOT coincidentally
        # trip the trailer check either.
        rec = bytes([0x01, 0xFD, 0x08, 0x32, 0x00] + [0x00] * 8)
        self.assertEqual(len(rec), 13)
        payload = bytes([0x01]) + bytes.fromhex("F30001") + rec + bytes([0x0D, 0xFD])
        result = m.decode_lq(payload, table_policy="raw")
        self.assertEqual(result["mode"], "detailed")
        self.assertEqual(len(result["rolls"][0]["frames"]), 1)
        self.assertEqual(result["rolls"][0]["frames"][0]["shutter_speed"], "0xfd")

    def test_multi_roll_f3_immediately_after_trailer_fd(self):
        payload = (
            bytes([0x00])
            + bytes.fromhex("F30001") + bytes.fromhex("013c083200") + bytes([0x0D, 0xFD])
            + bytes.fromhex("F30002") + bytes.fromhex("027d093301") + bytes([0x0C, 0xFD])
        )
        result = m.decode_lq(payload, table_policy="raw")
        self.assertEqual(result["roll_count"], 2)
        self.assertEqual(result["rolls"][0]["roll_number"], 1)
        self.assertEqual(result["rolls"][1]["roll_number"], 2)
        self.assertEqual(result["rolls"][1]["frames"][0]["frame_number"], 2)

    def test_empty_roll_zero_frames(self):
        payload = bytes([0x00]) + bytes.fromhex("F30001") + bytes([0x0D, 0xFD])
        result = m.decode_lq(payload, table_policy="raw")
        self.assertEqual(result["rolls"][0]["frame_count"], 0)
        self.assertEqual(result["rolls"][0]["film_speed_raw"], "0x0d")

    def test_truncated_roll_missing_trailer_raises(self):
        payload = bytes([0x00]) + bytes.fromhex("F30001") + bytes.fromhex("013c083200")
        with self.assertRaises(m.ProtocolError):
            m.decode_lq(payload, table_policy="raw")

    def test_truncated_frame_record_raises(self):
        payload = bytes([0x00]) + bytes.fromhex("F30001") + bytes.fromhex("013c")
        with self.assertRaises(m.ProtocolError):
            m.decode_lq(payload, table_policy="raw")

    def test_unexpected_roll_start_byte_raises(self):
        payload = bytes([0x00]) + bytes.fromhex("F30001") + bytes.fromhex("013c083200") + bytes([0x0D, 0xFD, 0x99])
        with self.assertRaises(m.ProtocolError):
            m.decode_lq(payload, table_policy="raw")


# ---------------------------------------------------------------------------
# _load_value_table — P1: display column, CSV quoting, correct filenames
# ---------------------------------------------------------------------------

class TestValueTableLoader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.patcher = mock.patch.object(
            m, "__file__", str(Path(self.tmpdir) / "f100_readonly.py")
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_tsv(self, filename, rows):
        path = Path(self.tmpdir) / filename
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["raw_hex", "raw_decimal", "display"])
            writer.writerows(rows)

    def test_loads_display_column_not_raw_decimal(self):
        self._write_tsv("lq_shutter_speed_table.tsv", [["0x00", "0", "1\""]])
        table = m._load_value_table("shutter")
        self.assertEqual(table[0x00], '1"')  # display, not "0" (raw_decimal)

    def test_csv_quoting_roundtrips_embedded_quote(self):
        # This is exactly the real table's 0xFD row shape: a display value
        # ending in a literal double-quote (inch/seconds mark).
        self._write_tsv("lq_shutter_speed_table.tsv", [["0xFD", "253", '1.5"']])
        table = m._load_value_table("shutter")
        self.assertEqual(table[0xFD], '1.5"')

    def test_real_shutter_filename_is_lq_shutter_speed_table(self):
        # The old (buggy) filename must NOT be what gets read.
        self._write_tsv("lq_shutter_table.tsv", [["0x00", "0", "wrong file"]])
        table = m._load_value_table("shutter")
        self.assertIsNone(table)  # correct filename absent -> None, not the wrong file

        self._write_tsv("lq_shutter_speed_table.tsv", [["0x00", "0", "1\""]])
        table = m._load_value_table("shutter")
        self.assertEqual(table[0x00], '1"')

    def test_short_rows_skipped_not_crashed(self):
        path = Path(self.tmpdir) / "lq_aperture_table.tsv"
        path.write_text(
            "raw_hex\traw_decimal\tdisplay\n0x00\t0\n0x01\t1\tf/1.4\n", encoding="utf-8"
        )
        table = m._load_value_table("aperture")
        self.assertNotIn(0x00, table)
        self.assertEqual(table[0x01], "f/1.4")

    def test_strict_policy_rejects_short_rows(self):
        path = Path(self.tmpdir) / "lq_aperture_table.tsv"
        path.write_text(
            "raw_hex\traw_decimal\tdisplay\n0x00\t0\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(m.ProtocolError, "fewer than 3 columns"):
            m._load_value_table("aperture", missing_policy="strict")

    def test_missing_table_explicit_raw_policy_returns_none(self):
        table = m._load_value_table("shutter", missing_policy="raw")
        self.assertIsNone(table)

    def test_missing_table_warn_policy_is_visible(self):
        with self.assertWarnsRegex(RuntimeWarning, "value table missing"):
            table = m._load_value_table("shutter", missing_policy="warn")
        self.assertIsNone(table)

    def test_missing_table_strict_policy_fails_closed(self):
        with self.assertRaisesRegex(FileNotFoundError, "value table missing"):
            m._load_value_table("shutter", missing_policy="strict")

    def test_unknown_table_name_is_programmer_error(self):
        with self.assertRaisesRegex(ValueError, "unknown value table name"):
            m._load_value_table("ev_compensation")

    def test_decode_lq_uses_loaded_display_values(self):
        self._write_tsv(
            "lq_shutter_speed_table.tsv",
            [["0x3c", "60", "1/1000"], ["0xfd", "253", '1.5"']],
        )
        payload = bytes.fromhex("00 F3 00 01 01 FD 00 00 00 0D FD".replace(" ", ""))
        result = m.decode_lq(payload, table_policy="raw")
        self.assertEqual(result["rolls"][0]["frames"][0]["shutter_speed"], '1.5"')

    def test_decode_lq_loads_ev_table_under_correct_key(self):
        self._write_tsv(
            "lq_ev_compensation_table.tsv",
            [["0x00", "0", "+0.0"], ["0x01", "1", "+0.1"], ["0x02", "2", "+0.2"]],
        )
        rec = bytes([1, 0x3C, 8, 0x32, 0, 0x32, 0x32, 8, 8, 0, 1, 2, 0])
        payload = bytes([0x01]) + bytes.fromhex("F30001") + rec + bytes([0x0D, 0xFD])
        result = m.decode_lq(payload, table_dir=Path(self.tmpdir), table_policy="raw")
        frame = result["rolls"][0]["frames"][0]
        self.assertEqual(frame["manual_ev_diff"], "+0.0")
        self.assertEqual(frame["exposure_comp"], "+0.1")
        self.assertEqual(frame["flash_comp"], "+0.2")

    def test_validate_value_tables_checks_all_four_files(self):
        for name, filename in m._VALUE_TABLE_FILENAMES.items():
            self._write_tsv(filename, [["0x00", "0", f"{name}-display"]])
        report = m.validate_value_tables(Path(self.tmpdir))
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["tables"]), set(m._VALUE_TABLE_FILENAMES))
        self.assertTrue(all(item["rows"] == 1 for item in report["tables"].values()))

    def test_validate_value_tables_reports_missing_files(self):
        report = m.validate_value_tables(Path(self.tmpdir))
        self.assertFalse(report["ok"])
        self.assertTrue(all("missing" in item["errors"] for item in report["tables"].values()))


class _FakeSerialReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""


class _ExclusiveSerialModule:
    EIGHTBITS = 8
    PARITY_EVEN = "E"
    STOPBITS_TWO = 2

    def __init__(self):
        self.locked_ports = set()
        self.instances = []

    def Serial(self, **kwargs):
        module = self

        class Handle:
            def __init__(self):
                object.__setattr__(self, "events", [("construct", kwargs)])
                object.__setattr__(self, "is_open", False)
                object.__setattr__(self, "port", None)

            def __setattr__(self, name, value):
                object.__setattr__(self, name, value)
                if name in {"dtr", "rts", "port"}:
                    self.events.append((name, value))

            def open(self):
                self.events.append(("open", self.port))
                if self.port in module.locked_ports:
                    raise OSError("advisory lock rejected")
                module.locked_ports.add(self.port)
                object.__setattr__(self, "is_open", True)

            def close(self):
                self.events.append(("close", self.port))
                if self.is_open:
                    module.locked_ports.remove(self.port)
                    object.__setattr__(self, "is_open", False)

        handle = Handle()
        self.instances.append(handle)
        return handle


class TestTransportResponsePolicy(unittest.TestCase):
    @staticmethod
    def _frame(data=b"\x01", status=0x61):
        return (1 + len(data)).to_bytes(2, "big") + bytes([status]) + data

    def test_timeout_and_quiet_window_are_configurable(self):
        link = m.F100Link("fake", response_timeout=0.02, post_frame_quiet=0.001)
        self.assertEqual(link.response_timeout, 0.02)
        self.assertEqual(link.post_frame_quiet, 0.001)
        with self.assertRaises(ValueError):
            m.F100Link("fake", response_timeout=0)
        with self.assertRaises(ValueError):
            m.F100Link("fake", post_frame_quiet=-1)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    m.F100Link("fake", response_timeout=value)
                with self.assertRaises(ValueError):
                    m.F100Link("fake", post_frame_quiet=value)

    def test_open_minimizes_dtr_rts_and_requests_advisory_lock(self):
        serial_module = _ExclusiveSerialModule()
        link = _authorized_link()
        with mock.patch.object(m, "serial", serial_module):
            with link._open() as first:
                kwargs = first.events[0][1]
                self.assertIsNone(kwargs["port"])
                self.assertTrue(kwargs["exclusive"])
                self.assertEqual(kwargs["write_timeout"], m.WRITE_TIMEOUT_S)
                self.assertEqual(
                    first.events[1:5],
                    [
                        ("dtr", True),
                        ("rts", False),
                        ("port", "/dev/cu.fixture"),
                        ("open", "/dev/cu.fixture"),
                    ],
                )
                with self.assertRaisesRegex(OSError, "advisory lock rejected"):
                    with _authorized_link()._open():
                        pass
                self.assertEqual(
                    serial_module.instances[-1].events[-1],
                    ("close", "/dev/cu.fixture"),
                )

    def test_direct_request_api_cannot_open_without_p3_authorization(self):
        serial_module = _ExclusiveSerialModule()
        link = m.F100Link("/dev/cu.fixture")
        with mock.patch.object(m, "serial", serial_module):
            with self.assertRaisesRegex(m.ProtocolError, "verified CLI P3 binding"):
                link.request("CQ")
        self.assertEqual(serial_module.instances, [])

    def test_open_success_capture_failure_closes_handle(self):
        serial_module = _ExclusiveSerialModule()
        link = _authorized_link()
        link.capture.record.side_effect = [None, RuntimeError("capture failure"), None]
        with mock.patch.object(m, "serial", serial_module):
            with self.assertRaisesRegex(RuntimeError, "capture failure"):
                with link._open():
                    pass
        self.assertEqual(serial_module.instances[0].events[-1], ("close", "/dev/cu.fixture"))

    def test_request_rejects_write_unknown_and_payload_before_open(self):
        link = m.F100Link("fake")
        with mock.patch.object(link, "_open") as open_port:
            for opcode, payload in (("NP", b""), ("ZZ", b""), ("CQ", b"\x01")):
                with self.subTest(opcode=opcode, payload=payload):
                    with self.assertRaises(m.ProtocolError):
                        link.request(opcode, payload)
            open_port.assert_not_called()

    def test_request_rejects_lq_without_live_capability_before_open(self):
        link = m.F100Link("fake")
        with mock.patch.object(link, "_open") as open_port:
            with self.assertRaisesRegex(m.ProtocolError, "experimental-live capability"):
                link.request("LQ")
            open_port.assert_not_called()

    def test_authorization_issuer_rejects_self_asserted_binding_dictionary(self):
        integration = {
            "session_id": "fixture-p3-001",
            "serial_port": "/dev/cu.fixture",
            "verified_before_device_open": True,
        }
        capture = mock.Mock()
        capture.integration = dict(integration)
        with self.assertRaisesRegex(m.ProtocolError, "verified P3 binding"):
            m._issue_live_transport_authorization(
                port="/dev/cu.fixture",
                capture=capture,
                verified_binding=integration,
            )

    def test_request_rejections_are_logged_before_open(self):
        capture = mock.Mock()
        capture.integration = {}
        link = m.F100Link("fake", capture=capture)
        cases = (("NP", b""), ("LQ", b""), ("CQ", b"\x01"), (object(), b""))
        with mock.patch.object(link, "_open") as open_port:
            for opcode, payload in cases:
                with self.subTest(opcode=opcode):
                    with self.assertRaises(m.ProtocolError):
                        link.request(opcode, payload)
        open_port.assert_not_called()
        rejected = [
            call for call in capture.record.call_args_list
            if call.args and call.args[0] == "tx_rejected"
        ]
        self.assertEqual(len(rejected), len(cases))

    def test_rejection_log_failure_does_not_open_or_write(self):
        capture = mock.Mock()
        capture.integration = {}
        capture.record.side_effect = OSError("fixture log failure")
        link = m.F100Link("fake", capture=capture)
        with mock.patch.object(link, "_open") as open_port:
            with self.assertRaises(m.ProtocolError):
                link.request("NP")
        open_port.assert_not_called()

    def test_final_write_boundary_rejects_disallowed_or_mismatched_bytes(self):
        link = m.F100Link("fake")
        port = mock.Mock()
        cases = (
            (b"NP\x00\x00", "command", "NP", None),
            (b"CQ\x00\x01\x01", "command", "CQ", None),
            (b"MQ\x00\x00", "command", "CQ", None),
            (b"\x01", "attention", "CQ", None),
            (b"CQ\x00\x00", "fixture", "CQ", None),
            (b"LQ\x00\x00", "command", "LQ", None),
            (b"LQ\x00\x00", "command", "LQ", object()),
        )
        for data, role, opcode, capability in cases:
            with self.subTest(data=data, role=role, opcode=opcode):
                with self.assertRaises(m.ProtocolError):
                    link._write(
                        port,
                        data,
                        role=role,
                        opcode=opcode,
                        live_capability=capability,
                    )
        port.write.assert_not_called()

    def test_final_write_rejects_hostile_bytes_subclass(self):
        class HostileBytes(bytes):
            def __ne__(self, _other):
                return False

        port = mock.Mock()
        with self.assertRaises(m.ProtocolError):
            m.F100Link("fake")._write(
                port, HostileBytes(b"NP\x00\x00"), role="command", opcode="CQ"
            )
        port.write.assert_not_called()

    def test_final_write_boundary_allows_exact_lq_frame_with_capability(self):
        link = m.F100Link("fake")
        port = mock.Mock()
        port.write.return_value = 4
        link._write(
            port,
            b"LQ\x00\x00",
            role="command",
            opcode="LQ",
            live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY,
        )
        port.write.assert_called_once_with(b"LQ\x00\x00")

    def test_lq_preflight_requires_capability_before_mq(self):
        link = m.F100Link("fake")
        link.request = mock.Mock()
        with self.assertRaisesRegex(m.ProtocolError, "experimental-live capability"):
            link.request_lq_camera_companion_preflight()
        link.request.assert_not_called()

    def test_exactly_one_response_frame_is_returned(self):
        link = m.F100Link("fake", response_timeout=0.02, post_frame_quiet=0.001)
        response = link._read_single_response(
            _FakeSerialReader([self._frame(b"\x11")]), "LQ"
        )
        self.assertEqual(response.data, b"\x11")

    def test_second_response_frame_is_not_silently_discarded(self):
        link = m.F100Link("fake", response_timeout=0.02, post_frame_quiet=0.001)
        reader = _FakeSerialReader([self._frame(b"\x11") + self._frame(b"\x22")])
        with self.assertRaisesRegex(m.ProtocolError, "exactly one response frame, got 2"):
            link._read_single_response(reader, "LQ")

    def test_partial_trailing_frame_is_not_silently_discarded(self):
        link = m.F100Link("fake", response_timeout=0.02, post_frame_quiet=0.001)
        reader = _FakeSerialReader([self._frame(b"\x11") + b"\x00\x05\x61"])
        with self.assertRaisesRegex(m.ProtocolError, "trailing partial response"):
            link._read_single_response(reader, "LQ")

    def test_preflight_fails_closed_after_second_mq_non_success(self):
        link = m.F100Link("fake")
        failed = m.CameraResponse(status=0x79, data=b"", raw=b"")
        link.request = mock.Mock(side_effect=[failed, failed])
        with mock.patch.object(m.time, "sleep"):
            with self.assertRaises(m.ObservedNonSuccessStatus):
                link.request_lq_camera_companion_preflight(
                    live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY
                )

    def test_preflight_fails_closed_on_oq_non_success(self):
        link = m.F100Link("fake")
        mq = m.CameraResponse(status=0x61, data=b"\x00", raw=b"")
        oq = m.CameraResponse(status=0x79, data=b"", raw=b"")
        link.request = mock.Mock(side_effect=[mq, oq])
        with mock.patch.object(m.time, "sleep"):
            with self.assertRaises(m.ObservedNonSuccessStatus):
                link.request_lq_camera_companion_preflight(
                    live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY
                )

    def test_preflight_rejects_wrong_mq_length(self):
        link = m.F100Link("fake")
        mq = m.CameraResponse(status=0x61, data=b"", raw=b"")
        link.request = mock.Mock(return_value=mq)
        with mock.patch.object(m.time, "sleep"):
            with self.assertRaisesRegex(m.ProtocolError, "MQ preflight data must be 1 byte"):
                link.request_lq_camera_companion_preflight(
                    live_capability=m._EXPERIMENTAL_LQ_LIVE_CAPABILITY
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
