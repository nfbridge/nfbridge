#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Shared fail-closed verifier for F100 live-device evidence binding.

This module only reads JSON evidence.  It never enumerates or opens devices,
controls UTM, launches Nikon software, or transmits camera commands.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import f100_usb_admission as admission
import f100_operation_scope as operations


PLAN_SCHEMA = "f100-orchestration-plan/0.2"
ADMISSION_SCHEMA = "f100-usb-admission-report/0.1"
GATE_SCHEMA = "f100-offline-utm-forwarding-gate/0.2"
DISCOVERY_SESSION_SCHEMA = "f100-offline-usb-discovery/0.1"
DISCOVERY_SUMMARY_SCHEMA = "f100-offline-usb-discovery-summary/0.1"
APPROVAL_SCHEMA = "f100-offline-usb-manual-approval/0.1"
SNAPSHOT_SCHEMA = "f100-usb-admission-snapshot/0.2"
POLICY_SCHEMA = "f100-usb-admission-policy/0.1"
PREAUTH_SUMMARY_SCHEMA = "f100-usb-preauth-summary/0.2"

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SERIAL_RE = re.compile(r"^/dev/cu\.[A-Za-z0-9._-]+$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class BindingError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_binding(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _load(path: Path, label: str) -> Dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BindingError(f"{label} JSON root is not an object")
    value["_source_file_sha256"] = hashlib.sha256(payload).hexdigest()
    return value


def _validate_self_hash(
    value: Dict[str, Any], field: str, label: str
) -> None:
    declared = value.get(field)
    if not isinstance(declared, str):
        raise BindingError(f"{label} is missing {field}")
    unhashed = {key: item for key, item in value.items() if key != "_source_file_sha256"}
    unhashed.pop(field, None)
    if _canonical_hash(unhashed) != declared:
        raise BindingError(f"{label} self-hash mismatch")


def _document_hash(value: Dict[str, Any]) -> str:
    return _canonical_hash(
        {key: item for key, item in value.items() if key != "_source_file_sha256"}
    )


def _without_source_hash(value: Dict[str, Any]) -> Dict[str, Any]:
    return {key: item for key, item in value.items() if key != "_source_file_sha256"}


def _report_semantics(value: Dict[str, Any]) -> Dict[str, Any]:
    result = _without_source_hash(value)
    result.pop("generated_utc", None)
    result.pop("report_sha256_without_this_field", None)
    return result


def _load_sealed(path: Path, schema: str, hash_field: str, label: str) -> Dict[str, Any]:
    value = _load(path, label)
    compatible = {
        DISCOVERY_SESSION_SCHEMA: {DISCOVERY_SESSION_SCHEMA, "f100-offline-usb-discovery/0.2"},
        DISCOVERY_SUMMARY_SCHEMA: {DISCOVERY_SUMMARY_SCHEMA, "f100-offline-usb-discovery-summary/0.2"},
    }.get(schema, {schema})
    if value.get("schema") not in compatible:
        raise BindingError(f"{label} schema mismatch")
    _validate_self_hash(value, hash_field, label)
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise BindingError(f"{label} generated_utc is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BindingError(f"{label} generated_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise BindingError(f"{label} generated_utc has no timezone")
    return parsed.astimezone(timezone.utc)


def _require_fresh(
    value: Dict[str, Any], label: str, now: datetime, max_age_seconds: float
) -> None:
    age = (now - _parse_utc(value.get("generated_utc"), label)).total_seconds()
    if age < -60 or age > max_age_seconds:
        raise BindingError(f"{label} is stale or from the future")


def _validate_first_use_binding(
    *,
    orchestration_plan: Path,
    admission_report: Path,
    forwarding_gate: Path,
    integration_session_id: str,
    serial_port: str,
    expected_mode: str,
    expected_command: Optional[str] = None,
    expected_guest_com: Optional[str] = None,
    max_age_seconds: float = 900,
    require_freshness: bool = True,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Validate the complete P3 chain and return manifest-ready bindings."""
    if not SESSION_ID_RE.fullmatch(integration_session_id):
        raise BindingError("integration session ID is malformed")
    if not SERIAL_RE.fullmatch(serial_port):
        raise BindingError("serial port must be an exact /dev/cu.* path")
    if expected_mode not in {"mac-client", "mac-relay", "windows-direct"}:
        raise BindingError("live binding mode is unsupported")
    if not (0 < max_age_seconds <= 3600):
        raise BindingError("binding maximum age must be between 0 and 3600 seconds")

    try:
        plan_path = orchestration_plan.expanduser().resolve(strict=True)
        report_path = admission_report.expanduser().resolve(strict=True)
        gate_path = forwarding_gate.expanduser().resolve(strict=True)
    except OSError as exc:
        raise BindingError("a required live-binding file is unavailable: " + str(exc)) from exc

    session_dir = plan_path.parent
    admission_dir = session_dir / "mac-admission"
    if plan_path != session_dir / "orchestration-plan.json":
        raise BindingError("orchestration plan path is not canonical for the session")
    if report_path != admission_dir / "report.json":
        raise BindingError("admission report path is not canonical for the session")
    if gate_path != admission_dir / "utm-forwarding-gate.json":
        raise BindingError("forwarding gate path is not canonical for the session")
    if session_dir.name != integration_session_id:
        raise BindingError("session directory does not match the integration session ID")

    plan = _load(plan_path, "orchestration plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise BindingError("orchestration plan schema mismatch")
    _validate_self_hash(plan, "plan_sha256_without_this_field", "orchestration plan")
    if plan.get("session_id") != integration_session_id:
        raise BindingError("orchestration plan session ID mismatch")
    if plan.get("mode") != expected_mode:
        raise BindingError("orchestration plan mode mismatch")
    if expected_mode == "windows-direct":
        if plan.get("serial_port") not in (None, serial_port):
            raise BindingError("orchestration plan serial port mismatch")
    elif plan.get("serial_port") != serial_port:
        raise BindingError("orchestration plan serial port mismatch")
    if plan.get("execution_authorized") is not False:
        raise BindingError("orchestration plan improperly claims execution authorization")
    if plan.get("lq_default_live_blocked") is not True:
        raise BindingError("orchestration plan lost the default LQ block")
    operation = None
    if expected_command in operations.NEW_SCOPES:
        operations.validate_live_policy(plan)
        operation = operations.validate(plan.get("operation"), expected_command)
        if (expected_mode != "mac-client" or plan.get("np_dp_ep_implemented") is not True
                or plan.get("dp_implemented") is not False
                or plan.get("automatic_write_retry") is not False):
            raise BindingError("invalid single-operation scope")
    elif expected_command == "maintenance":
        if (plan.get("np_dp_ep_implemented") is not True or
            plan.get("maintenance_action") != "erase-and-detailed" or
            plan.get("dp_implemented") is not False or
            plan.get("automatic_write_retry") is not False):
            raise BindingError("invalid maintenance scope")
    elif plan.get("np_dp_ep_implemented") is not False:
        raise BindingError("orchestration plan lost the NP/DP/EP boundary")
    capture_nonce = plan.get("capture_binding_nonce")
    if not isinstance(capture_nonce, str) or not HASH_RE.fullmatch(capture_nonce):
        raise BindingError("orchestration plan capture binding nonce is malformed")
    if expected_command is not None and plan.get("mac_command") != expected_command:
        raise BindingError("orchestration plan command mismatch")
    if expected_guest_com is not None and plan.get("guest_com") != expected_guest_com:
        raise BindingError("orchestration plan guest COM mismatch")

    discovery_session = _load_sealed(
        admission_dir / "session.json",
        DISCOVERY_SESSION_SCHEMA,
        "self_sha256_without_this_field",
        "discovery session",
    )
    if discovery_session.get("identity_check_only") is not False:
        raise BindingError("discovery session is identity-check-only")
    expected_vid = discovery_session.get("expected_vid")
    expected_pid = discovery_session.get("expected_pid")
    if not all(isinstance(value, str) for value in (expected_vid, expected_pid)):
        raise BindingError("discovery session VID/PID binding is missing")

    before = _load_sealed(
        admission_dir / "before.json", SNAPSHOT_SCHEMA,
        "self_sha256_without_this_field", "before snapshot"
    )
    after = _load_sealed(
        admission_dir / "after.json", SNAPSHOT_SCHEMA,
        "self_sha256_without_this_field", "after snapshot"
    )
    policy = _load_sealed(
        admission_dir / "policy.json", POLICY_SCHEMA,
        "self_sha256_without_this_field", "candidate policy"
    )
    summary = _load_sealed(
        admission_dir / "discovery-summary.json", DISCOVERY_SUMMARY_SCHEMA,
        "self_sha256_without_this_field", "discovery summary"
    )
    if discovery_session["schema"].rsplit("/", 1)[1] != summary["schema"].rsplit("/", 1)[1]:
        raise BindingError("discovery session/summary schema versions differ")
    for field, expected in (
        ("identity_check_only", False),
        ("expected_vid", expected_vid),
        ("expected_pid", expected_pid),
        ("before_snapshot_sha256", _document_hash(before)),
        ("after_snapshot_sha256", _document_hash(after)),
        ("candidate_policy_sha256", _document_hash(policy)),
    ):
        if summary.get(field) != expected:
            raise BindingError("discovery summary binding mismatch: " + field)
    if summary.get("status") != "REVIEW_REQUIRED":
        raise BindingError("discovery summary is not reviewable")

    report = _load(report_path, "admission report")
    if report.get("schema") != ADMISSION_SCHEMA:
        raise BindingError("admission report schema mismatch")
    _validate_self_hash(report, "report_sha256_without_this_field", "admission report")
    if report.get("status") != "PASS":
        raise BindingError("admission report is not PASS")
    if report.get("manual_review_required_even_on_pass") is not True:
        raise BindingError("admission report lacks the manual-review boundary")
    if report.get("safe_to_forward_automatically") is not False:
        raise BindingError("admission report permits automatic forwarding")
    if report.get("badusb_prevention_claim") is not False:
        raise BindingError("admission report lacks the no-BadUSB-proof boundary")
    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise BindingError("admission report input bindings are missing")
    for field, expected in (
        ("before_snapshot_sha256", _document_hash(before)),
        ("after_snapshot_sha256", _document_hash(after)),
        ("policy_sha256", _document_hash(policy)),
    ):
        if inputs.get(field) != expected:
            raise BindingError("admission report input mismatch: " + field)
    candidate_path = admission_dir / "candidate-report.json"
    candidate_report = (
        _load_sealed(candidate_path, ADMISSION_SCHEMA, "report_sha256_without_this_field", "candidate report")
        if candidate_path.exists() else report
    )
    if summary.get("candidate_report_sha256") != _document_hash(candidate_report):
        raise BindingError("discovery summary candidate report mismatch")
    if _report_semantics(candidate_report) != _report_semantics(report):
        raise BindingError("candidate report and approved report semantics differ")
    delta = report.get("delta")
    serial_paths = delta.get("new_serial_paths") if isinstance(delta, dict) else None
    if not isinstance(serial_paths, list) or serial_port not in serial_paths:
        raise BindingError("admission report is not bound to the exact serial port")

    try:
        recomputed_report = admission.evaluate(
            _without_source_hash(before),
            _without_source_hash(after),
            _without_source_hash(policy),
        )
    except (TypeError, ValueError) as exc:
        raise BindingError("admission inputs fail semantic evaluation: " + str(exc)) from exc
    if _report_semantics(report) != _report_semantics(recomputed_report):
        raise BindingError("admission report disagrees with recomputed snapshot policy")
    recomputed_delta = recomputed_report["delta"]
    new_usb = recomputed_delta.get("new_usb_devices")
    new_serial = recomputed_delta.get("new_serial_paths")
    if not isinstance(new_usb, list) or len(new_usb) != 1:
        raise BindingError("admission delta must contain exactly one new USB identity")
    # macOS may expose both callout and dial-in nodes for one USB serial interface.
    expected_pair = sorted([serial_port, "/dev/tty." + serial_port[len("/dev/cu."):]])
    if new_serial != [serial_port] and new_serial != expected_pair:
        raise BindingError("admission delta must contain exactly the approved serial port or its cu/tty pair")
    candidate = new_usb[0]
    if (
        str(candidate.get("vendor_id", "")).lower() != expected_vid
        or str(candidate.get("product_id", "")).lower() != expected_pid
    ):
        raise BindingError("admission delta USB VID/PID mismatch")
    if summary.get("new_usb_devices") != new_usb or summary.get("new_serial_paths") != new_serial:
        raise BindingError("discovery summary disagrees with recomputed admission delta")

    approval_path = admission_dir / "approval.json"
    approval = _load_sealed(
        approval_path, APPROVAL_SCHEMA,
        "self_sha256_without_this_field", "manual approval"
    )
    if approval.get("serial_port") != serial_port:
        raise BindingError("manual approval serial port mismatch")
    if approval.get("expected_vid") != expected_vid or approval.get("expected_pid") != expected_pid:
        raise BindingError("manual approval VID/PID mismatch")
    assertions = approval.get("operator_assertions")
    if not isinstance(assertions, dict) or any(
        assertions.get(field) is not True
        for field in (
            "device_label_and_topology_physically_reviewed",
            "logical_check_is_not_badusb_or_electrical_proof",
            "f100_remains_disconnected",
        )
    ):
        raise BindingError("manual approval assertions are incomplete")
    if approval.get("manual_utm_forwarding_only") is not True:
        raise BindingError("manual approval permits an unsupported action")
    if approval.get("report_file_sha256") != report["_source_file_sha256"]:
        raise BindingError("manual approval report binding mismatch")
    devices = summary.get("new_usb_devices")
    if not isinstance(devices, list) or len(devices) != 1 or approval.get(
        "fingerprint_sha256"
    ) != devices[0].get("fingerprint_sha256"):
        raise BindingError("manual approval fingerprint mismatch")
    if serial_port not in summary.get("new_serial_paths", []):
        raise BindingError("discovery summary serial port mismatch")
    if approval.get("preauth_summary_binding") != discovery_session.get("preauth_summary_binding"):
        raise BindingError("manual approval preauth binding mismatch")
    preauth_binding = discovery_session.get("preauth_summary_binding")
    if preauth_binding is not None:
        if not isinstance(preauth_binding, dict):
            raise BindingError("preauth summary binding is malformed")
        preauth_path_value = preauth_binding.get("path")
        preauth_hash = preauth_binding.get("file_sha256")
        if not isinstance(preauth_path_value, str) or not isinstance(preauth_hash, str):
            raise BindingError("preauth summary binding fields are malformed")
        try:
            preauth_path = Path(preauth_path_value).expanduser().resolve(strict=True)
        except OSError as exc:
            raise BindingError("bound preauth summary is unavailable: " + str(exc)) from exc
        if preauth_path != admission_dir / "preauth" / "preauth-summary.json":
            raise BindingError("bound preauth summary path is not canonical")
        preauth = _load_sealed(
            preauth_path,
            PREAUTH_SUMMARY_SCHEMA,
            "self_sha256_without_this_field",
            "bound preauth summary",
        )
        if preauth["_source_file_sha256"] != preauth_hash:
            raise BindingError("bound preauth summary file changed")
        for field, expected in (
            ("status", preauth_binding.get("status")),
            ("integration_session_id", integration_session_id),
            ("admission_session_path_sha256", _path_binding(admission_dir)),
            ("binding_nonce", preauth_binding.get("binding_nonce")),
        ):
            if preauth.get(field) != expected or preauth_binding.get(field) != expected:
                raise BindingError("bound preauth summary binding mismatch: " + field)
        if preauth.get("status") not in {"AUTH_REQUEST_OBSERVED", "NO_ENUMERATION"}:
            raise BindingError("bound preauth summary is not eligible")
        if preauth.get("eligible_only_for_cable_only_postauth_enumeration") is not True:
            raise BindingError("bound preauth summary eligibility changed")
        if preauth.get("safe_to_connect_f100") is not False:
            raise BindingError("bound preauth summary camera boundary changed")

    gate = _load(gate_path, "UTM forwarding gate")
    if gate.get("schema") != GATE_SCHEMA:
        raise BindingError("UTM forwarding gate schema mismatch")
    _validate_self_hash(gate, "self_sha256_without_this_field", "UTM forwarding gate")
    if gate.get("status") != "PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW":
        raise BindingError("UTM forwarding gate is not a final PASS")
    if gate.get("integration_session_id") != integration_session_id:
        raise BindingError("UTM forwarding gate session ID mismatch")
    if gate.get("admission_session_path_sha256") != _path_binding(admission_dir):
        raise BindingError("UTM forwarding gate admission path mismatch")
    if gate.get("serial_port") != serial_port:
        raise BindingError("UTM forwarding gate serial port mismatch")
    if gate.get("admission_report_file") != str(report_path):
        raise BindingError("UTM forwarding gate admission report path mismatch")
    if gate.get("admission_report_file_sha256") != report["_source_file_sha256"]:
        raise BindingError("UTM forwarding gate admission report hash mismatch")
    try:
        approval_path = approval_path.resolve(strict=True)
    except OSError as exc:
        raise BindingError("manual approval file is unavailable: " + str(exc)) from exc
    if gate.get("manual_approval_file") != str(approval_path):
        raise BindingError("UTM forwarding gate manual approval path mismatch")
    approval_hash = approval["_source_file_sha256"]
    if gate.get("manual_approval_file_sha256") != approval_hash:
        raise BindingError("UTM forwarding gate manual approval hash mismatch")
    if gate.get("fingerprint_sha256") != approval.get("fingerprint_sha256"):
        raise BindingError("UTM forwarding gate fingerprint mismatch")
    if gate.get("current_enumeration_matches_reviewed_after") is not True:
        raise BindingError("UTM forwarding gate lacks the final enumeration match")
    if gate.get("network_gate_status") == "EXEMPT_USER_REVIEWED_CABLE":
        import f100_offline_usb_gate as offline_gate
        try:
            exception_binding = offline_gate.reviewed_cable_network_exception(admission_dir, approval)
        except (ValueError, OSError) as exc:
            raise BindingError("network exception invalid: " + str(exc)) from exc
        if gate.get("network_exception_binding") != exception_binding:
            raise BindingError("network exception binding mismatch")
    elif gate.get("network_gate_status") != "PASS":
        raise BindingError("UTM forwarding gate network check is not PASS")
    if gate.get("utm_was_controlled") is not False:
        raise BindingError("UTM forwarding gate improperly claims UTM control")
    if gate.get("serial_device_was_opened") is not False:
        raise BindingError("UTM forwarding gate improperly claims serial access")
    if gate.get("safe_to_forward_automatically") is not False:
        raise BindingError("UTM forwarding gate permits automatic forwarding")

    if require_freshness:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _require_fresh(report, "admission report", current, max_age_seconds)
        _require_fresh(gate, "UTM forwarding gate", current, max_age_seconds)

    return {
        **({"operation": operation, "operation_scope": expected_command,
            "candidate_live_blocked": False,
            "live_policy_revision": operations.LIVE_POLICY_REVISION} if operation is not None else {}),
        "binding_schema": "f100-live-evidence-binding/0.2",
        "session_id": integration_session_id,
        "serial_port": serial_port,
        "orchestration_plan_file": str(plan_path),
        "orchestration_plan_sha256": plan["_source_file_sha256"],
        "admission_report_file": str(report_path),
        "admission_report_sha256": report["_source_file_sha256"],
        "manual_approval_file": str(approval_path),
        "manual_approval_sha256": approval_hash,
        "utm_forwarding_gate_file": str(gate_path),
        "utm_forwarding_gate_sha256": gate["_source_file_sha256"],
        "mode": expected_mode,
        "guest_com": expected_guest_com,
        "command": expected_command,
        "capture_binding_nonce": capture_nonce,
        "preauth_summary_binding": preauth_binding,
        "verified_before_device_open": True,
    }


def validate_live_binding(**kwargs):
    """Keep the original chain intact; dispatch only the explicit reconnect schema."""
    report = _load(Path(kwargs['admission_report']), 'admission report')
    if report.get('schema') == 'f100-cable-reconnect-report/0.1':
        import f100_reconnect
        return f100_reconnect.validate_binding(**kwargs)
    return _validate_first_use_binding(**kwargs)
