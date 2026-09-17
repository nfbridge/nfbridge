#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline-only regression tests for the P3 live evidence binding."""

import argparse
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import f100_live_binding as subject
import f100_orchestrator as orchestrator


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestLiveBinding(unittest.TestCase):
    def _bundle(self, root: str, mode: str = "mac-client", serial_paths=None):
        values = {
            "root": Path(root),
            "session_id": "fixture-p3-001",
            "mode": mode,
            "program": None if mode == "mac-client" else "CameraCompanion",
            "guest_com": None if mode == "mac-client" else "COM3",
            "serial_port": "/dev/cu.fixture",
            "vm_pty": None if mode == "mac-client" else "/dev/ttys1",
            "mac_command": "cq" if mode == "mac-client" else None,
        }
        plan_path = orchestrator.create_plan(argparse.Namespace(**values))
        session = plan_path.parent
        admission = session / "mac-admission"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot_base = {
            "schema": subject.SNAPSHOT_SCHEMA,
            "snapshot_complete": True,
            "usb_devices": [],
            "hid_devices": [],
            "disk_identifiers": [],
            "network_interfaces": [],
            "system_extension_lines": [],
            "serial_paths": [],
            "serial_bsd_clients": [],
        }
        sealed = {}
        before = dict(snapshot_base)
        after = dict(snapshot_base)
        after["usb_devices"] = [{
            "fingerprint_sha256": "a" * 64,
            "vendor_id": "0x0403",
            "product_id": "0x6001",
            "serial_client_registry_ids": [],
        }]
        after["serial_paths"] = serial_paths if serial_paths is not None else ["/dev/cu.fixture"]
        before["usb_enumeration"] = {
            "primary": "ioreg_IOUSBHostDevice",
            "crosscheck": "system_profiler_SPUSBDataType",
            "crosscheck_status": "BOTH_EMPTY",
            "ioreg_device_count": 0,
            "system_profiler_device_count": 0,
        }
        after["usb_enumeration"] = {
            "primary": "ioreg_IOUSBHostDevice",
            "crosscheck": "system_profiler_SPUSBDataType",
            "crosscheck_status": "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE",
            "ioreg_device_count": 1,
            "system_profiler_device_count": 0,
        }
        policy = subject.admission.default_policy()
        policy["allowed_new_usb_fingerprints"] = ["a" * 64]
        policy["allowed_new_serial_path_regexes"] = [re.escape(path) for path in after["serial_paths"]]
        for filename, value in (
            ("before.json", before),
            ("after.json", after),
            ("policy.json", policy),
        ):
            value["self_sha256_without_this_field"] = subject._canonical_hash(value)
            _write(admission / filename, value)
            sealed[filename] = value
        discovery_session = {
            "schema": subject.DISCOVERY_SESSION_SCHEMA,
            "expected_vid": "0x0403",
            "expected_pid": "0x6001",
            "identity_check_only": False,
            "preauth_summary_binding": None,
        }
        discovery_session["self_sha256_without_this_field"] = subject._canonical_hash(discovery_session)
        _write(admission / "session.json", discovery_session)
        report = subject.admission.evaluate(
            sealed["before.json"], sealed["after.json"], sealed["policy.json"]
        )
        _write(admission / "report.json", report)
        summary = {
            "schema": subject.DISCOVERY_SUMMARY_SCHEMA,
            "status": "REVIEW_REQUIRED",
            "identity_check_only": False,
            "expected_vid": "0x0403",
            "expected_pid": "0x6001",
            "before_snapshot_sha256": subject._canonical_hash(sealed["before.json"]),
            "after_snapshot_sha256": subject._canonical_hash(sealed["after.json"]),
            "candidate_policy_sha256": subject._canonical_hash(sealed["policy.json"]),
            "candidate_report_sha256": subject._canonical_hash(report),
            "new_usb_devices": [dict(after["usb_devices"][0])],
            "new_serial_paths": sorted(after["serial_paths"]),
        }
        summary["self_sha256_without_this_field"] = subject._canonical_hash(summary)
        _write(admission / "discovery-summary.json", summary)
        approval = {
            "schema": subject.APPROVAL_SCHEMA,
            "fingerprint_sha256": "a" * 64,
            "serial_port": "/dev/cu.fixture",
            "expected_vid": "0x0403",
            "expected_pid": "0x6001",
            "report_file_sha256": _sha(admission / "report.json"),
            "operator_assertions": {
                "device_label_and_topology_physically_reviewed": True,
                "logical_check_is_not_badusb_or_electrical_proof": True,
                "f100_remains_disconnected": True,
            },
            "preauth_summary_binding": None,
            "manual_utm_forwarding_only": True,
        }
        approval["self_sha256_without_this_field"] = subject._canonical_hash(approval)
        _write(admission / "approval.json", approval)
        gate = {
            "schema": subject.GATE_SCHEMA,
            "generated_utc": now,
            "status": "PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW",
            "integration_session_id": session.name,
            "admission_session_path_sha256": subject._path_binding(admission),
            "serial_port": "/dev/cu.fixture",
            "fingerprint_sha256": "a" * 64,
            "admission_report_file": str((admission / "report.json").resolve()),
            "admission_report_file_sha256": _sha(admission / "report.json"),
            "manual_approval_file": str((admission / "approval.json").resolve()),
            "manual_approval_file_sha256": _sha(admission / "approval.json"),
            "current_enumeration_matches_reviewed_after": True,
            "network_gate_status": "PASS",
            "utm_was_controlled": False,
            "serial_device_was_opened": False,
            "safe_to_forward_automatically": False,
        }
        gate["self_sha256_without_this_field"] = subject._canonical_hash(gate)
        _write(admission / "utm-forwarding-gate.json", gate)
        return session

    def _reseal_chain(self, session: Path) -> None:
        admission = session / "mac-admission"
        before = json.loads((admission / "before.json").read_text())
        after = json.loads((admission / "after.json").read_text())
        policy = json.loads((admission / "policy.json").read_text())
        report_path = admission / "report.json"
        report = json.loads(report_path.read_text())
        report["inputs"] = {
            "before_snapshot_sha256": subject._canonical_hash(before),
            "after_snapshot_sha256": subject._canonical_hash(after),
            "policy_sha256": subject._canonical_hash(policy),
        }
        report.pop("report_sha256_without_this_field", None)
        report["report_sha256_without_this_field"] = subject._canonical_hash(report)
        _write(report_path, report)
        summary_path = admission / "discovery-summary.json"
        summary = json.loads(summary_path.read_text())
        summary.update({
            "before_snapshot_sha256": subject._canonical_hash(before),
            "after_snapshot_sha256": subject._canonical_hash(after),
            "candidate_policy_sha256": subject._canonical_hash(policy),
            "candidate_report_sha256": subject._canonical_hash(report),
        })
        summary.pop("self_sha256_without_this_field", None)
        summary["self_sha256_without_this_field"] = subject._canonical_hash(summary)
        _write(summary_path, summary)
        approval_path = admission / "approval.json"
        approval = json.loads(approval_path.read_text())
        approval["report_file_sha256"] = _sha(report_path)
        approval.pop("self_sha256_without_this_field", None)
        approval["self_sha256_without_this_field"] = subject._canonical_hash(approval)
        _write(approval_path, approval)
        gate_path = admission / "utm-forwarding-gate.json"
        gate = json.loads(gate_path.read_text())
        gate["admission_report_file_sha256"] = _sha(report_path)
        gate["manual_approval_file_sha256"] = _sha(approval_path)
        gate.pop("self_sha256_without_this_field", None)
        gate["self_sha256_without_this_field"] = subject._canonical_hash(gate)
        _write(gate_path, gate)

    def test_candidate_report_can_precede_approved_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            admission = session / "mac-admission"
            report = json.loads((admission / "report.json").read_text())
            report["generated_utc"] = "2026-01-01T00:00:00Z"
            report.pop("report_sha256_without_this_field")
            report["report_sha256_without_this_field"] = subject._canonical_hash(report)
            _write(admission / "candidate-report.json", report)
            summary = json.loads((admission / "discovery-summary.json").read_text())
            summary["candidate_report_sha256"] = subject._canonical_hash(report)
            summary.pop("self_sha256_without_this_field")
            summary["self_sha256_without_this_field"] = subject._canonical_hash(summary)
            _write(admission / "discovery-summary.json", summary)
            kwargs = dict(orchestration_plan=session / "orchestration-plan.json",
                          admission_report=admission / "report.json",
                          forwarding_gate=admission / "utm-forwarding-gate.json",
                          integration_session_id=session.name, serial_port="/dev/cu.fixture",
                          expected_mode="mac-client", expected_command="cq")
            self.assertTrue(subject.validate_live_binding(**kwargs)["verified_before_device_open"])
            report["delta"]["new_serial_paths"] = ["/dev/cu.other"]
            report.pop("report_sha256_without_this_field")
            report["report_sha256_without_this_field"] = subject._canonical_hash(report)
            _write(admission / "candidate-report.json", report)
            summary["candidate_report_sha256"] = subject._canonical_hash(report)
            summary.pop("self_sha256_without_this_field")
            summary["self_sha256_without_this_field"] = subject._canonical_hash(summary)
            _write(admission / "discovery-summary.json", summary)
            with self.assertRaisesRegex(subject.BindingError, "semantics differ"):
                subject.validate_live_binding(**kwargs)

    def test_network_exception_is_explicit_bound_and_revalidated(self):
        import f100_offline_usb_gate as gate_tool
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            admission = session / "mac-admission"
            approval = json.loads((admission / "approval.json").read_text())
            value = {key: approval[key] for key in ("expected_vid", "expected_pid", "fingerprint_sha256", "serial_port")}
            value.update(schema="f100-reviewed-cable-network-exception/0.1",
                         integration_session_id=session.name,
                         admission_session_path_sha256=subject._path_binding(admission),
                         scope="network-isolation-only", user_authorized=True,
                         authorization_source="explicit fixture authorization")
            value["self_sha256_without_this_field"] = subject._canonical_hash(value)
            exception = admission / "reviewed-cable-network-exception.json"
            _write(exception, value)
            gate_path = admission / "utm-forwarding-gate.json"
            gate = json.loads(gate_path.read_text())
            gate["network_gate_status"] = "EXEMPT_USER_REVIEWED_CABLE"
            gate["network_exception_binding"] = gate_tool.reviewed_cable_network_exception(admission, approval)
            gate.pop("self_sha256_without_this_field")
            gate["self_sha256_without_this_field"] = subject._canonical_hash(gate)
            _write(gate_path, gate)
            kwargs = dict(orchestration_plan=session / "orchestration-plan.json",
                          admission_report=admission / "report.json", forwarding_gate=gate_path,
                          integration_session_id=session.name, serial_port="/dev/cu.fixture",
                          expected_mode="mac-client", expected_command="cq")
            self.assertTrue(subject.validate_live_binding(**kwargs)["verified_before_device_open"])
            for field, replacement in (("user_authorized", False), ("serial_port", "/dev/cu.other"),
                                       ("integration_session_id", "other"), ("scope", "all")):
                changed = dict(value)
                changed[field] = replacement
                changed.pop("self_sha256_without_this_field")
                changed["self_sha256_without_this_field"] = subject._canonical_hash(changed)
                _write(exception, changed)
                with self.assertRaises(subject.BindingError):
                    subject.validate_live_binding(**kwargs)
            exception.unlink()
            with self.assertRaises(subject.BindingError):
                subject.validate_live_binding(**kwargs)

    def test_real_macos_pair_and_unrelated_nodes(self):
        for paths, accepted in (
            (["/dev/cu.fixture", "/dev/tty.fixture"], True),
            (["/dev/cu.fixture", "/dev/tty.other"], False),
            (["/dev/cu.fixture", "/dev/cu.other", "/dev/tty.fixture"], False),
            (["/dev/tty.fixture"], False),
        ):
            with self.subTest(paths=paths), tempfile.TemporaryDirectory() as temporary:
                session = self._bundle(temporary, serial_paths=paths)
                kwargs = dict(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=session / "mac-admission/report.json",
                    forwarding_gate=session / "mac-admission/utm-forwarding-gate.json",
                    integration_session_id=session.name, serial_port="/dev/cu.fixture",
                    expected_mode="mac-client", expected_command="cq",
                )
                if accepted:
                    self.assertTrue(subject.validate_live_binding(**kwargs)["verified_before_device_open"])
                else:
                    with self.assertRaises(subject.BindingError):
                        subject.validate_live_binding(**kwargs)

    def test_exact_client_chain_returns_manifest_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            binding = subject.validate_live_binding(
                orchestration_plan=session / "orchestration-plan.json",
                admission_report=session / "mac-admission/report.json",
                forwarding_gate=session / "mac-admission/utm-forwarding-gate.json",
                integration_session_id=session.name,
                serial_port="/dev/cu.fixture",
                expected_mode="mac-client",
                expected_command="cq",
            )
            self.assertTrue(binding["verified_before_device_open"])
            self.assertEqual(binding["session_id"], session.name)
            self.assertEqual(binding["serial_port"], "/dev/cu.fixture")
            self.assertRegex(binding["capture_binding_nonce"], r"^[0-9a-f]{64}$")
            for key in (
                "orchestration_plan_sha256",
                "admission_report_sha256",
                "manual_approval_sha256",
                "utm_forwarding_gate_sha256",
            ):
                self.assertRegex(binding[key], r"^[0-9a-f]{64}$")

    def test_tampered_report_is_rejected_through_final_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            report_path = session / "mac-admission/report.json"
            report = json.loads(report_path.read_text())
            report["delta"]["new_serial_paths"] = ["/dev/cu.other"]
            _write(report_path, report)
            with self.assertRaisesRegex(subject.BindingError, "self-hash|serial port"):
                subject.validate_live_binding(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=report_path,
                    forwarding_gate=session / "mac-admission/utm-forwarding-gate.json",
                    integration_session_id=session.name,
                    serial_port="/dev/cu.fixture",
                    expected_mode="mac-client",
                    expected_command="cq",
                )

    def test_bound_preauth_file_is_independently_revalidated(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            admission = session / "mac-admission"
            preauth_path = admission / "preauth/preauth-summary.json"
            preauth = {
                "schema": subject.PREAUTH_SUMMARY_SCHEMA,
                "status": "NO_ENUMERATION",
                "integration_session_id": session.name,
                "admission_session_path_sha256": subject._path_binding(admission),
                "binding_nonce": "b" * 64,
                "eligible_only_for_cable_only_postauth_enumeration": True,
                "safe_to_connect_f100": False,
            }
            preauth["self_sha256_without_this_field"] = subject._canonical_hash(preauth)
            _write(preauth_path, preauth)
            binding = {
                "path": str(preauth_path.resolve()),
                "file_sha256": _sha(preauth_path),
                "status": "NO_ENUMERATION",
                "integration_session_id": session.name,
                "admission_session_path_sha256": subject._path_binding(admission),
                "binding_nonce": "b" * 64,
            }
            discovery_path = admission / "session.json"
            discovery = json.loads(discovery_path.read_text())
            discovery["preauth_summary_binding"] = binding
            discovery.pop("self_sha256_without_this_field")
            discovery["self_sha256_without_this_field"] = subject._canonical_hash(discovery)
            _write(discovery_path, discovery)
            approval_path = admission / "approval.json"
            approval = json.loads(approval_path.read_text())
            approval["preauth_summary_binding"] = binding
            approval.pop("self_sha256_without_this_field")
            approval["self_sha256_without_this_field"] = subject._canonical_hash(approval)
            _write(approval_path, approval)
            gate_path = admission / "utm-forwarding-gate.json"
            gate = json.loads(gate_path.read_text())
            gate["manual_approval_file_sha256"] = _sha(approval_path)
            gate.pop("self_sha256_without_this_field")
            gate["self_sha256_without_this_field"] = subject._canonical_hash(gate)
            _write(gate_path, gate)

            result = subject.validate_live_binding(
                orchestration_plan=session / "orchestration-plan.json",
                admission_report=admission / "report.json",
                forwarding_gate=gate_path,
                integration_session_id=session.name,
                serial_port="/dev/cu.fixture",
                expected_mode="mac-client",
                expected_command="cq",
            )
            self.assertEqual(result["preauth_summary_binding"], binding)

            preauth["safe_to_connect_f100"] = True
            preauth.pop("self_sha256_without_this_field")
            preauth["self_sha256_without_this_field"] = subject._canonical_hash(preauth)
            _write(preauth_path, preauth)
            with self.assertRaisesRegex(subject.BindingError, "file changed"):
                subject.validate_live_binding(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=admission / "report.json",
                    forwarding_gate=gate_path,
                    integration_session_id=session.name,
                    serial_port="/dev/cu.fixture",
                    expected_mode="mac-client",
                    expected_command="cq",
                )

    def test_foreign_gate_path_and_session_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            gate = session / "mac-admission/utm-forwarding-gate.json"
            foreign = session / "mac-admission/foreign-gate.json"
            foreign.write_bytes(gate.read_bytes())
            with self.assertRaisesRegex(subject.BindingError, "not canonical"):
                subject.validate_live_binding(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=session / "mac-admission/report.json",
                    forwarding_gate=foreign,
                    integration_session_id=session.name,
                    serial_port="/dev/cu.fixture",
                    expected_mode="mac-client",
                    expected_command="cq",
                )

    def test_stub_manual_approval_is_rejected_even_if_gate_is_rehashed(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            admission = session / "mac-admission"
            _write(admission / "approval.json", {"schema": "fixture-approval"})
            gate_path = admission / "utm-forwarding-gate.json"
            gate = json.loads(gate_path.read_text())
            gate["manual_approval_file_sha256"] = _sha(admission / "approval.json")
            gate.pop("self_sha256_without_this_field")
            gate["self_sha256_without_this_field"] = subject._canonical_hash(gate)
            _write(gate_path, gate)
            with self.assertRaisesRegex(subject.BindingError, "manual approval schema"):
                subject.validate_live_binding(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=admission / "report.json",
                    forwarding_gate=gate_path,
                    integration_session_id=session.name,
                    serial_port="/dev/cu.fixture",
                    expected_mode="mac-client",
                    expected_command="cq",
                )

    def test_semantically_forged_report_is_rejected(self):
        mutations = ("empty_delta", "empty_allowlist", "wrong_vid", "violations")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                session = self._bundle(temporary)
                admission = session / "mac-admission"
                if mutation == "empty_delta":
                    before = json.loads((admission / "before.json").read_text())
                    after = dict(before)
                    after.pop("self_sha256_without_this_field", None)
                    after["self_sha256_without_this_field"] = subject._canonical_hash(after)
                    _write(admission / "after.json", after)
                elif mutation == "empty_allowlist":
                    policy = json.loads((admission / "policy.json").read_text())
                    policy["allowed_new_usb_fingerprints"] = []
                    policy["allowed_new_serial_path_regexes"] = []
                    policy.pop("self_sha256_without_this_field")
                    policy["self_sha256_without_this_field"] = subject._canonical_hash(policy)
                    _write(admission / "policy.json", policy)
                elif mutation == "wrong_vid":
                    after = json.loads((admission / "after.json").read_text())
                    after["usb_devices"][0]["vendor_id"] = "0x067b"
                    after.pop("self_sha256_without_this_field")
                    after["self_sha256_without_this_field"] = subject._canonical_hash(after)
                    _write(admission / "after.json", after)
                    report = json.loads((admission / "report.json").read_text())
                    report["delta"]["new_usb_devices"][0]["vendor_id"] = "0x067b"
                    _write(admission / "report.json", report)
                    summary = json.loads((admission / "discovery-summary.json").read_text())
                    summary["new_usb_devices"][0]["vendor_id"] = "0x067b"
                    _write(admission / "discovery-summary.json", summary)
                else:
                    report = json.loads((admission / "report.json").read_text())
                    report["violations"] = ["forged violation"]
                    _write(admission / "report.json", report)
                self._reseal_chain(session)
                with self.assertRaises(subject.BindingError):
                    subject.validate_live_binding(
                        orchestration_plan=session / "orchestration-plan.json",
                        admission_report=admission / "report.json",
                        forwarding_gate=admission / "utm-forwarding-gate.json",
                        integration_session_id=session.name,
                        serial_port="/dev/cu.fixture",
                        expected_mode="mac-client",
                        expected_command="cq",
                    )

    def test_manual_approval_is_hashed_from_the_loaded_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = self._bundle(temporary)
            with mock.patch.object(
                subject, "_sha256", side_effect=AssertionError("second path read")
            ):
                binding = subject.validate_live_binding(
                    orchestration_plan=session / "orchestration-plan.json",
                    admission_report=session / "mac-admission/report.json",
                    forwarding_gate=session / "mac-admission/utm-forwarding-gate.json",
                    integration_session_id=session.name,
                    serial_port="/dev/cu.fixture",
                    expected_mode="mac-client",
                    expected_command="cq",
                )
            self.assertTrue(binding["verified_before_device_open"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
