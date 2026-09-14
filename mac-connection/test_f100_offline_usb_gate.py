#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline-only tests for the supervised USB/UTM gate."""

import argparse
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import f100_offline_usb_gate as subject


FP = "a" * 64


def _snapshot(*, cable=False, hid=False):
    value = {
        "schema": "f100-usb-admission-snapshot/0.2",
        "snapshot_complete": True,
        "usb_devices": [],
        "hid_devices": [],
        "disk_identifiers": ["disk0"],
        "network_interfaces": ["lo0", "en0"],
        "system_extension_lines": ["baseline"],
        "serial_paths": [],
    }
    if cable:
        value["usb_devices"] = [{
            "_name": "PL2303 fixture",
            "vendor_id": "0x067b",
            "product_id": "0x2303",
            "tree_path": ["Generic USB Hub", "PL2303 fixture"],
            "fingerprint_sha256": FP,
        }]
        value["serial_paths"] = ["/dev/cu.fixture", "/dev/tty.fixture"]
    if hid:
        value["hid_devices"] = [{"fingerprint_sha256": "hid-new"}]
    count = len(value["usb_devices"])
    value["usb_enumeration"] = {
        "primary": "ioreg_IOUSBHostDevice",
        "crosscheck": "system_profiler_SPUSBDataType",
        "crosscheck_status": (
            "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE" if count else "BOTH_EMPTY"
        ),
        "ioreg_device_count": count,
        "system_profiler_device_count": 0,
    }
    return value


def _network(pass_value=True):
    return {
        "schema": subject.NETWORK_SCHEMA,
        "generated_utc": subject._utc_now(),
        "status": "PASS" if pass_value else "FAIL",
        "violations": [] if pass_value else ["network active"],
    }


def _run_args(path):
    return argparse.Namespace(
        session=Path(path),
        expected_vid="067b",
        expected_pid="2303",
        preauth_summary=None,
        ack_network_physically_isolated=True,
        ack_stable_usb_baseline=True,
        ack_camera_disconnected=True,
        ack_accessories_always_ask=True,
    )


def _preauth_summary(session, *, status="NO_ENUMERATION", eligible=True):
    session = Path(session).resolve()
    value = {
        "schema": subject.PREAUTH_SUMMARY_SCHEMA,
        "generated_utc": subject._utc_now(),
        "status": status,
        "violations": [] if eligible else ["fixture anomaly"],
        "eligible_only_for_cable_only_postauth_enumeration": eligible,
        "safe_to_connect_f100": False,
        "integration_session_id": session.parent.name,
        "admission_session_path_sha256": subject._path_binding(session),
        "binding_nonce": "c" * 64,
    }
    value["self_sha256_without_this_field"] = subject._canonical_hash(value)
    return value


def _offline_network_outputs():
    return {
        ("/sbin/route", "-n", "get", "default"): {
            "ok": True,
            "exit_code": 0,
            "stdout": b"",
            "stderr": "route: writing to routing socket: not in table\n",
        },
        ("/sbin/route", "-n", "get", "-inet6", "default"): {
            "ok": True,
            "exit_code": 0,
            "stdout": b"",
            "stderr": "route: writing to routing socket: not in table\n",
        },
        ("/sbin/ifconfig", "-l"): {
            "ok": True,
            "exit_code": 0,
            "stdout": b"lo0 en0 awdl0 utun0",
            "stderr": "",
        },
        ("/sbin/ifconfig", "en0"): {
            "ok": True,
            "exit_code": 0,
            "stdout": (
                b"en0: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500\n"
                b"\tinet6 fe80::1%en0\n\tstatus: inactive\n"
            ),
            "stderr": "",
        },
        ("/sbin/ifconfig", "awdl0"): {
            "ok": True,
            "exit_code": 0,
            "stdout": (
                b"awdl0: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1484\n"
                b"\tinet6 fe80::2%awdl0\n\tstatus: inactive\n"
            ),
            "stderr": "",
        },
        ("/sbin/ifconfig", "utun0"): {
            "ok": True,
            "exit_code": 0,
            "stdout": (
                b"utun0: flags=8010<POINTOPOINT,MULTICAST> mtu 1380\n"
                b"\tinet6 fe80::3%utun0\n\tstatus: inactive\n"
            ),
            "stderr": "",
        },
        ("/usr/sbin/networksetup", "-listallhardwareports"): {
            "ok": True,
            "exit_code": 0,
            "stdout": b"Hardware Port: Wi-Fi\nDevice: en0\n",
            "stderr": "",
        },
        ("/usr/sbin/networksetup", "-getairportpower", "en0"): {
            "ok": True,
            "exit_code": 0,
            "stdout": b"Wi-Fi Power (en0): Off\n",
            "stderr": "",
        },
    }


def _collect_network(outputs):
    return subject.collect_network_gate(
        runner=lambda command: copy.deepcopy(outputs[tuple(command)])
    )


class TestNetworkGate(unittest.TestCase):
    def test_active_network_and_wifi_fail(self):
        outputs = {
            ("/sbin/route", "-n", "get", "default"): (True, b"gateway: 1.2.3.4"),
            ("/sbin/route", "-n", "get", "-inet6", "default"): (False, b""),
            ("/sbin/ifconfig", "-l"): (True, b"lo0 en0"),
            ("/sbin/ifconfig", "en0"): (True, b"\tinet 10.0.0.2\n\tstatus: active\n"),
            ("/usr/sbin/networksetup", "-listallhardwareports"): (
                True, b"Hardware Port: Wi-Fi\nDevice: en0\n"
            ),
            ("/usr/sbin/networksetup", "-getairportpower", "en0"): (
                True, b"Wi-Fi Power (en0): On\n"
            ),
        }

        def runner(command):
            ok, data = outputs[tuple(command)]
            return {"ok": ok, "exit_code": 0 if ok else 1, "stdout": data, "stderr": ""}

        report = subject.collect_network_gate(runner=runner)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("default route" in item for item in report["violations"]))
        self.assertTrue(any("Wi-Fi power" in item for item in report["violations"]))

    def test_offline_network_passes_without_claiming_proof(self):
        report = _collect_network(_offline_network_outputs())
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["network_isolation_claim"])
        self.assertEqual(
            report["addressed_interfaces"], ["en0", "awdl0", "utun0"]
        )
        self.assertEqual(
            report["default_route_states"], {"ipv4": "absent", "ipv6": "absent"}
        )
        self.assertEqual(report["active_interfaces"], [])
        self.assertEqual(report["indeterminate_interfaces"], [])
        self.assertEqual(report["inactive_interfaces"], ["en0", "awdl0", "utun0"])
        self.assertIn("stdout_text", report["commands"]["interface_awdl0"])

    def test_route_absence_requires_clean_success_and_exact_message(self):
        cases = (
            {
                "ok": False,
                "exit_code": 1,
                "stdout": b"",
                "stderr": (
                    "route: writing to routing socket: not in table\n"
                    "Permission denied\n"
                ),
            },
            {
                "ok": False,
                "exit_code": -9,
                "stdout": b"",
                "stderr": "route: writing to routing socket: not in table\n",
            },
            {
                "ok": True,
                "exit_code": 0,
                "stdout": b"",
                "stderr": "prefix: not in table\n",
            },
        )
        for route_result in cases:
            with self.subTest(route_result=route_result):
                outputs = _offline_network_outputs()
                outputs[("/sbin/route", "-n", "get", "default")] = route_result
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["default_route_states"]["ipv4"], "unknown")

    def test_interface_enumeration_and_classification_fail_closed(self):
        cases = (
            (b"", None),
            (b"lo0 en0!", None),
            (b"lo0 en0", b""),
            (
                b"lo0 en0",
                b"en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX> mtu 1500\n"
                b"\tinet 192.0.2.2 netmask 0xffffff00\n",
            ),
        )
        for interface_list, interface_output in cases:
            with self.subTest(
                interface_list=interface_list,
                interface_output=interface_output,
            ):
                outputs = _offline_network_outputs()
                outputs[("/sbin/ifconfig", "-l")]["stdout"] = interface_list
                if interface_output is not None:
                    outputs[("/sbin/ifconfig", "en0")]["stdout"] = interface_output
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")

    def test_ambiguous_or_contradictory_interface_records_fail_closed(self):
        cases = (
            b"en0: flags=0<> mtu 1500\n\tstatus: unavailable\n",
            b"en0: flags=999<GARBAGE> mtu 1500\n",
            (
                b"en0: flags=0<> mtu 1500\n"
                b"en0: flags=41<UP,RUNNING> mtu 1500\n"
            ),
            b"en0: flags=0<> mtu 1500\nen0: malformed secondary header\n",
        )
        for interface_output in cases:
            with self.subTest(interface_output=interface_output):
                outputs = _offline_network_outputs()
                outputs[("/sbin/ifconfig", "en0")]["stdout"] = interface_output
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("en0", report["indeterminate_interfaces"])

    def test_current_macos_inactive_media_overrides_administrative_up_flags(self):
        outputs = _offline_network_outputs()
        outputs[("/sbin/ifconfig", "en0")]["stdout"] = (
            b"en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
            b"\tinet6 fe80::1%en0 prefixlen 64 scopeid 0x9\n"
            b"\tmedia: autoselect\n"
            b"\tstatus: inactive\n"
        )
        report = _collect_network(outputs)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("en0", report["inactive_interfaces"])

    def test_malformed_interface_addresses_fail_before_state_classification(self):
        cases = (
            (
                b"utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
                b"\tstatus: inactive\n\tinet6 not-an-ip\n"
            ),
            (
                b"utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
                b"\tinet6 169.254.1.2 prefixlen 64\n"
            ),
            (
                b"utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
                b"\tinet6 fe80::1%%broken prefixlen 64\n"
            ),
        )
        for interface_output in cases:
            with self.subTest(interface_output=interface_output):
                outputs = _offline_network_outputs()
                outputs[("/sbin/ifconfig", "utun0")]["stdout"] = interface_output
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("utun0", report["indeterminate_interfaces"])

    def test_dormant_virtual_link_local_is_inactive_but_vpn_address_is_active(self):
        outputs = _offline_network_outputs()
        outputs[("/sbin/ifconfig", "utun0")]["stdout"] = (
            b"utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
            b"\tinet6 fe80::3%utun0 prefixlen 64 scopeid 0x12\n"
        )
        report = _collect_network(outputs)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("utun0", report["inactive_interfaces"])

        outputs[("/sbin/ifconfig", "utun0")]["stdout"] = (
            b"utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280\n"
            b"\tinet 100.122.173.24 --> 100.122.173.24 netmask 0xffffffff\n"
            b"\tinet6 fd7a:115c:a1e0::313a:ad19 prefixlen 48\n"
        )
        report = _collect_network(outputs)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("utun0", report["active_interfaces"])

    def test_unfamiliar_statusless_up_interface_remains_active(self):
        outputs = _offline_network_outputs()
        outputs[("/sbin/ifconfig", "en0")]["stdout"] = (
            b"en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
        )
        report = _collect_network(outputs)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("en0", report["active_interfaces"])

    def test_wifi_discovery_and_power_response_fail_closed(self):
        cases = (
            b"",
            b"Hardware Port: Wi-Fi\n",
            b"Hardware Port: Ethernet\nDevice: en5\n",
        )
        for hardware_output in cases:
            with self.subTest(hardware_output=hardware_output):
                outputs = _offline_network_outputs()
                outputs[
                    ("/usr/sbin/networksetup", "-listallhardwareports")
                ]["stdout"] = hardware_output
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")

        outputs = _offline_network_outputs()
        outputs[
            ("/usr/sbin/networksetup", "-getairportpower", "en0")
        ]["stdout"] = b"Wi-Fi Power (en9): Off\n"
        report = _collect_network(outputs)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("Wi-Fi power is not confirmed off: en0", report["violations"])

    def test_ambiguous_wifi_blocks_fail_without_selecting_first_device(self):
        cases = (
            b"Hardware Port: Wi-Fi\nDevice: en0\nDevice: en9\n",
            b"Hardware Port: Wi-Fi\nDevice: en0\nDevice : en9\n",
            (
                b"Hardware Port: Wi-Fi\nDevice: en0\n"
                b"Hardware Port: Wi-Fi\nDevice: en9\n"
            ),
            (
                b"Hardware Port: Wi-Fi\nDevice: en0\n"
                b"Hardware Port : Wi-Fi\nDevice: en9\n"
            ),
        )
        for hardware_output in cases:
            with self.subTest(hardware_output=hardware_output):
                outputs = _offline_network_outputs()
                outputs[
                    ("/usr/sbin/networksetup", "-listallhardwareports")
                ]["stdout"] = hardware_output
                report = _collect_network(outputs)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["wifi_devices"], [])

    def test_indeterminate_route_check_fails_closed(self):
        outputs = {
            ("/sbin/route", "-n", "get", "default"): {
                "ok": False,
                "exit_code": None,
                "stdout": b"",
                "stderr": "permission denied",
            },
            ("/sbin/route", "-n", "get", "-inet6", "default"): {
                "ok": True,
                "exit_code": 0,
                "stdout": b"",
                "stderr": "route: writing to routing socket: not in table\n",
            },
            ("/sbin/ifconfig", "-l"): {
                "ok": True, "exit_code": 0, "stdout": b"lo0 en0", "stderr": ""
            },
            ("/sbin/ifconfig", "en0"): {
                "ok": True,
                "exit_code": 0,
                "stdout": b"\tstatus: inactive\n",
                "stderr": "",
            },
            ("/usr/sbin/networksetup", "-listallhardwareports"): {
                "ok": True,
                "exit_code": 0,
                "stdout": b"Hardware Port: Wi-Fi\nDevice: en0\n",
                "stderr": "",
            },
            ("/usr/sbin/networksetup", "-getairportpower", "en0"): {
                "ok": True,
                "exit_code": 0,
                "stdout": b"Wi-Fi Power (en0): Off\n",
                "stderr": "",
            },
        }

        report = subject.collect_network_gate(
            runner=lambda command: outputs[tuple(command)]
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "cannot determine whether an IPv4 default route is present",
            report["violations"],
        )


class TestDiscovery(unittest.TestCase):
    def test_safe_delta_still_requires_manual_review(self):
        policy, report, summary = subject.derive_candidate(
            _snapshot(), _snapshot(cable=True), "0x067b", "0x2303"
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(summary["status"], "REVIEW_REQUIRED")
        self.assertFalse(summary["safe_to_forward_automatically"])
        self.assertEqual(policy["allowed_new_usb_fingerprints"], [FP])

    def test_identity_only_discovery_reports_ids_but_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "identity-session" / "mac-admission"
            session.parent.mkdir()
            args = _run_args(session)
            args.expected_vid = None
            args.expected_pid = None
            cable = _snapshot(cable=True)
            cable["serial_paths"] = []
            snapshots = iter((_snapshot(), cable))
            path = subject.run_discovery(
                args,
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            summary = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "REVIEW_REQUIRED")
            self.assertTrue(summary["identity_check_only"])
            self.assertIsNone(summary["expected_vid"])
            self.assertIsNone(summary["expected_pid"])
            self.assertEqual(summary["new_usb_devices"][0]["vendor_id"], "0x067b")
            self.assertEqual(summary["new_usb_devices"][0]["product_id"], "0x2303")
            self.assertEqual(summary["new_serial_paths"], [])

            summary["identity_check_only"] = False
            summary["self_sha256_without_this_field"] = subject._canonical_hash(
                {
                    key: value
                    for key, value in summary.items()
                    if key != "self_sha256_without_this_field"
                }
            )
            path.write_text(json.dumps(summary), encoding="utf-8")

            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            with self.assertRaisesRegex(subject.GateError, "cannot be promoted"):
                subject.approve_candidate(approve)
            self.assertFalse((session / "approval.json").exists())

    def test_discovery_summary_tamper_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            path = session / "discovery-summary.json"
            summary = json.loads(path.read_text(encoding="utf-8"))
            summary["expected_vid"] = "0xffff"
            path.write_text(json.dumps(summary), encoding="utf-8")
            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            with self.assertRaisesRegex(subject.GateError, "self-hash mismatch"):
                subject.approve_candidate(approve)
            summary["self_sha256_without_this_field"] = subject._canonical_hash(
                {
                    key: value
                    for key, value in summary.items()
                    if key != "self_sha256_without_this_field"
                }
            )
            path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(subject.GateError, "authoritative session"):
                subject.approve_candidate(approve)
            self.assertFalse((session / "approval.json").exists())

    def test_identity_only_session_cannot_reach_forwarding_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "identity-session" / "mac-admission"
            session.parent.mkdir()
            args = _run_args(session)
            args.expected_vid = None
            args.expected_pid = None
            cable = _snapshot(cable=True)
            cable["serial_paths"] = []
            snapshots = iter((_snapshot(), cable))
            subject.run_discovery(
                args,
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            forged_approval = {"preauth_summary_binding": None}
            forged_approval["self_sha256_without_this_field"] = (
                subject._canonical_hash(forged_approval)
            )
            (session / "approval.json").write_text(
                json.dumps(forged_approval), encoding="utf-8"
            )
            gate = argparse.Namespace(
                session=session,
                serial_port="/dev/cu.fixture",
                max_age_seconds=900,
            )
            with self.assertRaisesRegex(subject.GateError, "identity-check-only"):
                subject.gate_for_manual_forwarding(gate)
            self.assertFalse((session / "utm-forwarding-gate.json").exists())

    def test_new_hid_or_wrong_vid_is_a_hard_fail(self):
        after = _snapshot(cable=True, hid=True)
        _, _, summary = subject.derive_candidate(
            _snapshot(), after, "0x9999", "0x2303"
        )
        self.assertEqual(summary["status"], "FAIL")
        self.assertTrue(any("HID" in item for item in summary["violations"]))
        self.assertTrue(any("VID" in item for item in summary["violations"]))

    def test_run_stops_before_usb_snapshot_when_network_gate_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []

            def snapshot():
                calls.append("snapshot")
                return _snapshot()

            with self.assertRaisesRegex(subject.GateError, "network isolation"):
                subject.run_discovery(
                    _run_args(Path(temporary) / "session"),
                    snapshot_collector=snapshot,
                    network_collector=lambda: _network(False),
                    prompt=lambda _: "",
                )
            self.assertEqual(calls, [])

    def test_unverified_candidate_direct_topology_is_bound_and_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "direct-candidate"
            direct = _snapshot(cable=True)
            direct["usb_devices"][0]["tree_path"] = ["PL2303 fixture"]
            snapshots = iter((_snapshot(), direct))
            path = subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            summary = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "REVIEW_REQUIRED")
            self.assertTrue(summary["candidate_topology_observed"])
            self.assertEqual(summary["observed_candidate_topology"], ["PL2303 fixture"])

    def test_unchanged_existing_usb_accessory_may_remain_in_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "existing-accessory"
            existing = {
                "_name": "Existing audio interface",
                "vendor_id": "0x1111",
                "product_id": "0x2222",
                "tree_path": ["Existing audio interface"],
                "fingerprint_sha256": "e" * 64,
            }
            before = _snapshot()
            before["usb_devices"] = [copy.deepcopy(existing)]
            before["usb_enumeration"]["ioreg_device_count"] = 1
            before["usb_enumeration"]["crosscheck_status"] = "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE"
            after = _snapshot(cable=True)
            after["usb_devices"].append(copy.deepcopy(existing))
            after["usb_enumeration"]["ioreg_device_count"] = 2
            snapshots = iter((before, after))
            path = subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            summary = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "REVIEW_REQUIRED")
            self.assertEqual(len(summary["new_usb_devices"]), 1)
            self.assertEqual(summary["new_usb_devices"][0]["_name"], "PL2303 fixture")

    def test_candidate_with_malformed_topology_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "malformed-topology"
            malformed = _snapshot(cable=True)
            malformed["usb_devices"][0]["tree_path"] = ["Different device"]
            snapshots = iter((_snapshot(), malformed))
            path = subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            summary = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "FAIL")
            self.assertFalse(summary["candidate_topology_observed"])

    def test_existing_empty_orchestrator_admission_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "orchestrated" / "mac-admission"
            session.mkdir(parents=True)
            snapshots = iter((_snapshot(), _snapshot(cable=True)))
            path = subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            self.assertEqual(path.parent, session.resolve())
            self.assertFalse((session / "report.json").exists())

    def test_eligible_preauth_summary_is_auto_bound_into_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "orchestrated" / "mac-admission"
            preauth_dir = session / "preauth"
            preauth_dir.mkdir(parents=True)
            summary = _preauth_summary(session)
            (preauth_dir / "preauth-summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            snapshots = iter((_snapshot(), _snapshot(cable=True)))
            subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            record = json.loads((session / "session.json").read_text())
            binding = record["preauth_summary_binding"]
            self.assertEqual(binding["status"], "NO_ENUMERATION")
            self.assertEqual(len(binding["file_sha256"]), 64)
            self.assertEqual(binding["integration_session_id"], "orchestrated")
            self.assertEqual(binding["binding_nonce"], "c" * 64)

    def test_preauth_summary_cannot_be_reused_in_another_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "session-one" / "mac-admission"
            second = Path(temporary) / "session-two" / "mac-admission"
            foreign = first / "preauth" / "preauth-summary.json"
            foreign.parent.mkdir(parents=True)
            foreign.write_text(json.dumps(_preauth_summary(first)), encoding="utf-8")
            local = second / "preauth" / "preauth-summary.json"
            local.parent.mkdir(parents=True)
            local.write_bytes(foreign.read_bytes())
            with self.assertRaisesRegex(subject.GateError, "different integration session"):
                subject.run_discovery(
                    _run_args(second),
                    snapshot_collector=lambda: self.fail("must not collect"),
                    network_collector=lambda: self.fail("must not check network"),
                    prompt=lambda _: "",
                )

    def test_same_session_id_copied_to_another_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "source" / "same-id" / "mac-admission"
            second = Path(temporary) / "destination" / "same-id" / "mac-admission"
            local = second / "preauth" / "preauth-summary.json"
            local.parent.mkdir(parents=True)
            local.write_text(json.dumps(_preauth_summary(first)), encoding="utf-8")
            with self.assertRaisesRegex(subject.GateError, "different admission path"):
                subject.run_discovery(
                    _run_args(second),
                    snapshot_collector=lambda: self.fail("must not collect"),
                    network_collector=lambda: self.fail("must not check network"),
                    prompt=lambda _: "",
                )

    def test_external_preauth_summary_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "session-one" / "mac-admission"
            session.parent.mkdir(parents=True)
            external = Path(temporary) / "foreign-summary.json"
            external.write_text(json.dumps(_preauth_summary(session)), encoding="utf-8")
            args = _run_args(session)
            args.preauth_summary = external
            with self.assertRaisesRegex(subject.GateError, "current session"):
                subject.run_discovery(
                    args,
                    snapshot_collector=lambda: self.fail("must not collect"),
                    network_collector=lambda: self.fail("must not check network"),
                    prompt=lambda _: "",
                )

    def test_preauth_anomaly_cannot_enter_postauth_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "mac-admission"
            preauth_dir = session / "preauth"
            preauth_dir.mkdir(parents=True)
            summary = _preauth_summary(
                session, status="PREAUTH_ANOMALY", eligible=False
            )
            (preauth_dir / "preauth-summary.json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
            with self.assertRaisesRegex(subject.GateError, "not eligible"):
                subject.run_discovery(
                    _run_args(session),
                    snapshot_collector=lambda: _snapshot(),
                    network_collector=lambda: _network(True),
                    prompt=lambda _: "",
                )

    def test_bound_preauth_tamper_blocks_manual_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "mac-admission"
            preauth_dir = session / "preauth"
            preauth_dir.mkdir(parents=True)
            summary = _preauth_summary(session, status="AUTH_REQUEST_OBSERVED")
            preauth_path = preauth_dir / "preauth-summary.json"
            preauth_path.write_text(json.dumps(summary), encoding="utf-8")
            snapshots = iter((_snapshot(), _snapshot(cable=True)))
            subject.run_discovery(
                _run_args(session),
                snapshot_collector=lambda: next(snapshots),
                network_collector=lambda: _network(True),
                prompt=lambda _: "",
            )
            preauth_path.write_text(json.dumps({"tampered": True}), encoding="utf-8")
            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            with self.assertRaisesRegex(subject.GateError, "file changed"):
                subject.approve_candidate(approve)

    def test_bound_preauth_hash_and_decision_use_one_file_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preauth-summary.json"
            summary = {
                "schema": subject.PREAUTH_SUMMARY_SCHEMA,
                "status": "NO_ENUMERATION",
                "eligible_only_for_cable_only_postauth_enumeration": True,
                "safe_to_connect_f100": False,
                "integration_session_id": "fixture-session-001",
                "admission_session_path_sha256": "d" * 64,
                "binding_nonce": "c" * 64,
            }
            summary["self_sha256_without_this_field"] = subject._canonical_hash(summary)
            payload = json.dumps(summary).encode("utf-8")
            path.write_bytes(payload)
            binding = {
                "path": str(path),
                "file_sha256": subject.hashlib.sha256(payload).hexdigest(),
                "status": "NO_ENUMERATION",
                "integration_session_id": "fixture-session-001",
                "admission_session_path_sha256": "d" * 64,
                "binding_nonce": "c" * 64,
            }
            session_record = {"preauth_summary_binding": binding}
            with mock.patch.object(
                subject,
                "_load_json",
                side_effect=AssertionError("preauth path must not be read twice"),
            ):
                validated = subject._validate_bound_preauth(session_record)
            self.assertEqual(validated, binding)

    def _complete_discovery(self, root):
        snapshots = iter((_snapshot(), _snapshot(cable=True)))
        session = Path(root) / "session"
        subject.run_discovery(
            _run_args(session),
            snapshot_collector=lambda: next(snapshots),
            network_collector=lambda: _network(True),
            prompt=lambda _: "",
        )
        return session

    def test_discovery_inputs_are_self_hashed_and_summary_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            summary = json.loads(
                (session / "discovery-summary.json").read_text(encoding="utf-8")
            )
            for filename, schema, summary_field, label in (
                (
                    "before.json",
                    subject.admission.SNAPSHOT_SCHEMA,
                    "before_snapshot_sha256",
                    "before snapshot",
                ),
                (
                    "after.json",
                    subject.admission.SNAPSHOT_SCHEMA,
                    "after_snapshot_sha256",
                    "after snapshot",
                ),
                (
                    "candidate-policy.json",
                    subject.admission.POLICY_SCHEMA,
                    "candidate_policy_sha256",
                    "candidate policy",
                ),
            ):
                value = json.loads((session / filename).read_text(encoding="utf-8"))
                subject._validate_sealed_discovery_input(value, schema, label)
                self.assertEqual(
                    subject._canonical_hash(value), summary[summary_field]
                )

    def test_unsealed_discovery_input_tamper_cannot_be_approved(self):
        for filename in ("before.json", "after.json", "candidate-policy.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                session = self._complete_discovery(temporary)
                path = session / filename
                value = json.loads(path.read_text(encoding="utf-8"))
                value["tampered"] = True
                path.write_text(json.dumps(value), encoding="utf-8")
                approve = argparse.Namespace(
                    session=session,
                    fingerprint=FP,
                    serial_port="/dev/cu.fixture",
                    ack_device_label_physically_reviewed=True,
                    ack_logical_check_not_badusb_proof=True,
                )
                with self.assertRaisesRegex(subject.GateError, "self-hash mismatch"):
                    subject.approve_candidate(approve)
                self.assertFalse((session / "approval.json").exists())

    def test_rehashed_input_disagreement_and_gate_time_change_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            before_path = session / "before.json"
            before = json.loads(before_path.read_text(encoding="utf-8"))
            before["generated_utc"] = "2099-01-01T00:00:00Z"
            before["self_sha256_without_this_field"] = subject._canonical_hash(
                {
                    key: value
                    for key, value in before.items()
                    if key != "self_sha256_without_this_field"
                }
            )
            before_path.write_text(json.dumps(before), encoding="utf-8")
            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            with self.assertRaisesRegex(subject.GateError, "sealed discovery summary"):
                subject.approve_candidate(approve)

        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            subject.approve_candidate(approve)
            after_path = session / "after.json"
            after = json.loads(after_path.read_text(encoding="utf-8"))
            after["generated_utc"] = "2099-01-01T00:00:00Z"
            after["self_sha256_without_this_field"] = subject._canonical_hash(
                {
                    key: value
                    for key, value in after.items()
                    if key != "self_sha256_without_this_field"
                }
            )
            after_path.write_text(json.dumps(after), encoding="utf-8")
            report = json.loads((session / "report.json").read_text())
            created = datetime.fromisoformat(
                report["generated_utc"].replace("Z", "+00:00")
            )
            gate = argparse.Namespace(
                session=session,
                serial_port="/dev/cu.fixture",
                max_age_seconds=900,
            )
            with self.assertRaisesRegex(subject.GateError, "approved admission report"):
                subject.gate_for_manual_forwarding(
                    gate,
                    snapshot_collector=lambda: copy.deepcopy(_snapshot(cable=True)),
                    network_collector=lambda: _network(True),
                    now=created,
                )
            self.assertFalse((session / "utm-forwarding-gate.json").exists())

    def test_wrong_fingerprint_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            args = argparse.Namespace(
                session=session,
                fingerprint="b" * 64,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            with self.assertRaisesRegex(subject.GateError, "fingerprint"):
                subject.approve_candidate(args)

    def test_gate_rechecks_network_and_exact_enumeration(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._complete_discovery(temporary)
            approve = argparse.Namespace(
                session=session,
                fingerprint=FP,
                serial_port="/dev/cu.fixture",
                ack_device_label_physically_reviewed=True,
                ack_logical_check_not_badusb_proof=True,
            )
            subject.approve_candidate(approve)
            report = json.loads((session / "report.json").read_text())
            created = datetime.fromisoformat(report["generated_utc"].replace("Z", "+00:00"))
            gate = argparse.Namespace(
                session=session,
                serial_port="/dev/cu.fixture",
                max_age_seconds=900,
            )
            path = subject.gate_for_manual_forwarding(
                gate,
                snapshot_collector=lambda: copy.deepcopy(_snapshot(cable=True)),
                network_collector=lambda: _network(True),
                now=created,
            )
            value = json.loads(path.read_text())
            self.assertEqual(value["status"], "PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW")
            self.assertFalse(value["safe_to_forward_automatically"])
            self.assertFalse(value["utm_was_controlled"])
            self.assertEqual(value["schema"], subject.GATE_SCHEMA)
            self.assertEqual(value["serial_port"], "/dev/cu.fixture")
            self.assertEqual(
                value["admission_report_file_sha256"],
                subject.hashlib.sha256((session / "report.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                value["manual_approval_file_sha256"],
                subject.hashlib.sha256((session / "approval.json").read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
