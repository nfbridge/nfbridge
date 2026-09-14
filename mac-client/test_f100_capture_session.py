#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline regression tests for mandatory Mac-client evidence capture."""

import argparse
import hashlib
import importlib.util
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import f100_readonly as client
from f100_capture_session import CaptureSession, SCHEMA


class _FakePort:
    def __init__(self, response=b""):
        self.response = response
        self.writes = []
        self.closed = False
        self.opened = False
        self.port = None
        self.dtr = None
        self.rts = None

    def open(self):
        self.opened = True

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, _size):
        result, self.response = self.response, b""
        return result

    def close(self):
        self.closed = True


class _FakeSerialModule:
    EIGHTBITS = 8
    PARITY_EVEN = "E"
    STOPBITS_TWO = 2
    SerialException = OSError

    def __init__(self, port):
        self.port = port
        self.serial_kwargs = None

    def Serial(self, **kwargs):
        self.serial_kwargs = kwargs
        return self.port


class TestCaptureSession(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _capture(self, name="capture", integration=None):
        if integration is None:
            integration = {
                "binding_schema": "f100-live-evidence-binding/0.2",
                "session_id": "fixture-p3-001",
                "serial_port": "offline-fixture",
                "verified_before_device_open": True,
            }
        return CaptureSession(
            self.root / name,
            port="offline-fixture",
            command="cq",
            serial_config=client.SERIAL_CONFIG,
            integration=integration,
        )

    @staticmethod
    def _link(capture, **kwargs):
        verified = client._VerifiedLiveBinding(
            authority=client._VERIFIED_LIVE_BINDING_AUTHORITY,
            integration=dict(capture.integration),
        )
        authorization = client._issue_live_transport_authorization(
            port="offline-fixture",
            capture=capture,
            verified_binding=verified,
        )
        return client.F100Link(
            "offline-fixture",
            capture=capture,
            live_authorization=authorization,
            **kwargs,
        )

    def test_directional_payloads_and_hash_manifest(self):
        capture = self._capture()
        call_id = capture.tx_attempt(b"\x00CQ", role="fixture", opcode="CQ")
        capture.tx_result(
            call_id, b"\x00CQ", 3, role="fixture", opcode="CQ"
        )
        capture.rx(b"\x00\x02\x61\x01", opcode="CQ")
        manifest_path = capture.finish("success")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], SCHEMA)
        self.assertEqual(manifest["host_to_camera_bytes"], 3)
        self.assertEqual(manifest["camera_to_host_bytes"], 4)
        self.assertFalse(manifest["live_hardware_validation"])
        self.assertFalse(manifest["target_write_prevention_supported"])
        self.assertFalse(manifest["np_dp_ep_implemented"])
        self.assertTrue(manifest["lq_default_live_blocked"])
        for file_key, hash_key in (
            ("events_file", "events_sha256"),
            ("host_to_camera_file", "host_to_camera_sha256"),
            ("camera_to_host_file", "camera_to_host_sha256"),
        ):
            payload = (manifest_path.parent / manifest[file_key]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest[hash_key])

    def test_existing_evidence_directory_is_never_overwritten(self):
        (self.root / "capture").mkdir()
        with self.assertRaises(FileExistsError):
            self._capture()

    def test_manifest_preserves_exact_live_binding(self):
        integration = {
            "binding_schema": "f100-live-evidence-binding/0.1",
            "session_id": "fixture-p3-001",
            "serial_port": "/dev/cu.fixture",
            "verified_before_device_open": True,
        }
        capture = self._capture(integration=integration)
        manifest = json.loads(capture.finish("success").read_text(encoding="utf-8"))
        self.assertEqual(manifest["integration"], integration)

    def test_finish_is_idempotent(self):
        capture = self._capture()
        first = capture.finish("failure", "fixture")
        second = capture.finish("success")
        self.assertEqual(first, second)
        manifest = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(manifest["outcome"], "failure")

    def test_partial_write_records_only_materialized_prefix_and_fails(self):
        capture = self._capture()
        link = self._link(capture)
        port = mock.Mock()
        port.write.return_value = 2
        with self.assertRaisesRegex(client.ProtocolError, "short serial write"):
            link._write(port, b"CQ\x00\x00", role="command", opcode="CQ")
        capture.finish("failure", "short write fixture")
        self.assertEqual((capture.directory / "host-to-camera.bin").read_bytes(), b"CQ")
        manifest = json.loads(capture.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["tx_short_write_count"], 1)
        self.assertFalse(manifest["api_byte_reconstruction_complete"])

    def test_full_request_records_attention_command_response_and_close(self):
        raw_response = bytes.fromhex("00056101000080")
        fake_port = _FakePort(raw_response)
        fake_serial = _FakeSerialModule(fake_port)
        capture = self._capture()
        link = self._link(
            capture,
            response_timeout=0.05,
            post_frame_quiet=0,
        )
        with mock.patch.object(client, "serial", fake_serial), mock.patch.object(
            client.time, "sleep"
        ):
            response = link.request("CQ", expected_len=4)
        capture.finish("success")

        self.assertEqual(response.data, b"\x01\x00\x00\x80")
        self.assertEqual(fake_port.writes, [b"\x00", b"CQ\x00\x00"])
        self.assertTrue(fake_port.opened)
        self.assertTrue(fake_port.closed)
        self.assertTrue(fake_port.dtr)
        self.assertFalse(fake_port.rts)
        self.assertIsNone(fake_serial.serial_kwargs["port"])
        self.assertTrue(fake_serial.serial_kwargs["exclusive"])
        self.assertEqual(fake_serial.serial_kwargs["write_timeout"], client.WRITE_TIMEOUT_S)
        self.assertEqual(
            (capture.directory / "host-to-camera.bin").read_bytes(),
            b"\x00CQ\x00\x00",
        )
        self.assertEqual(
            (capture.directory / "camera-to-host.bin").read_bytes(), raw_response
        )
        events = [
            json.loads(line)
            for line in (capture.directory / "events.jsonl").read_text().splitlines()
        ]
        self.assertIn("serial_close_success", [item["event"] for item in events])
        self.assertIn("response_decoded", [item["event"] for item in events])

    def test_rejected_write_is_logged_without_payload_and_never_sent(self):
        capture = self._capture()
        link = self._link(capture)
        port = mock.Mock()
        with self.assertRaises(client.ProtocolError):
            link._write(port, b"NP\x00\x00", role="command", opcode="NP")
        capture.finish("failure", "expected rejection")
        port.write.assert_not_called()
        events = [json.loads(line) for line in capture.events_path.read_text().splitlines()]
        rejected = [item for item in events if item["event"] == "tx_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertNotIn("payload_hex", rejected[0])
        self.assertEqual((capture.directory / "host-to-camera.bin").read_bytes(), b"")

    def test_live_cli_requires_capture_directory_before_serial_access(self):
        with mock.patch.object(client.sys, "argv", ["f100_readonly.py", "cq"]), mock.patch(
            "sys.stderr"
        ):
            with self.assertRaises(SystemExit) as raised:
                client.main()
        self.assertEqual(raised.exception.code, 2)

    def test_live_cli_cannot_bypass_p3_binding(self):
        with mock.patch.object(
            client.sys,
            "argv",
            [
                "f100_readonly.py",
                "--port",
                "/dev/cu.fixture",
                "--capture-dir",
                str(self.root / "capture"),
                "cq",
            ],
        ), mock.patch.object(client, "_validate_cli_live_binding") as validator, mock.patch(
            "sys.stderr"
        ):
            with self.assertRaises(SystemExit) as raised:
                client.main()
        self.assertEqual(raised.exception.code, 2)
        validator.assert_not_called()

    def test_failed_p3_binding_stops_before_capture_or_serial_access(self):
        argv = [
            "f100_readonly.py",
            "--port", "/dev/cu.fixture",
            "--capture-dir", str(self.root / "capture"),
            "--integration-session-id", "fixture-p3-001",
            "--orchestration-plan", str(self.root / "orchestration-plan.json"),
            "--admission-report", str(self.root / "report.json"),
            "--utm-forwarding-gate", str(self.root / "utm-forwarding-gate.json"),
            "cq",
        ]
        with mock.patch.object(client.sys, "argv", argv), mock.patch.object(
            client,
            "_validate_cli_live_binding",
            side_effect=ValueError("final gate rejected"),
        ), mock.patch.object(client, "CaptureSession") as capture, mock.patch(
            "sys.stderr"
        ):
            with self.assertRaises(SystemExit) as raised:
                client.main()
        self.assertEqual(raised.exception.code, 2)
        capture.assert_not_called()

    def test_offline_fixture_cli_remains_capture_free(self):
        fixture = self.root / "lq.hex"
        fixture.write_text("00 F3 00 01 01 FD 00 00 00 0D FD\n", encoding="ascii")
        with mock.patch.object(
            client.sys,
            "argv",
            ["f100_readonly.py", "lq", "--fixture", str(fixture), "--table-policy", "raw"],
        ), mock.patch("sys.stdout"):
            self.assertEqual(client.main(), 0)

    @unittest.skipUnless(
        (Path(__file__).resolve().parent.parent / "mac-connection" / "f100_first_use_assistant.py").is_file(),
        "research-only cable ID assistant is excluded from this source package",
    )
    def test_cable_id_cli_uses_shared_identification_without_serial_access(self):
        evidence = self.root / "identity-evidence"
        argv = [
            "f100_readonly.py",
            "id",
            "--evidence-root",
            str(evidence),
            "--session-id",
            "fixture-id-001",
            "--observe-seconds",
            "1",
        ]
        with mock.patch.object(client.sys, "argv", argv), mock.patch.object(
            client, "run_cable_identification", return_value={"serial_port": "/dev/cu.fixture"}
        ) as identify, mock.patch.object(client, "F100Link") as link:
            self.assertEqual(client.main(), 0)
        identify.assert_called_once()
        called = identify.call_args.args[0]
        self.assertEqual(called.evidence_root, evidence)
        self.assertEqual(called.session_id, "fixture-id-001")
        self.assertEqual(called.observe_seconds, 1)
        link.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
