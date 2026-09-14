#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed session coordinator for the F100 observation toolchain.

This program never opens a serial device, controls UTM, starts a Nikon
application, or transmits a camera command.  It creates a portable session
plan, prints the next operator-controlled step, and verifies artifacts made by
the existing Mac and Windows tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import f100_live_binding as live_binding
import f100_operation_scope as operations


PLAN_SCHEMA = "f100-orchestration-plan/0.2"
REPORT_SCHEMA = "f100-orchestration-verification/0.3"
REFERENCE_AUTHORIZATION_SCHEMA = "f100-reference-action-authorization/0.2"
ADMISSION_SCHEMA = "f100-usb-admission-report/0.1"
WINDOWS_SCHEMA = "f100-capture-session/0.4"
RELAY_SCHEMA = "f100-mac-serial-relay/0.2"
MAC_CLIENT_SCHEMA = "f100-mac-capture/0.1"

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
COM_RE = re.compile(r"^COM([1-9][0-9]{0,4})$")
SERIAL_RE = re.compile(r"^/dev/cu\.[A-Za-z0-9._-]+$")
PTY_RE = re.compile(r"^/dev/ttys[0-9]+$")

MODES = (("windows-direct", "mac-relay", "mac-client")
         if (Path(__file__).resolve().parent / "f100_serial_relay.py").is_file()
         else ("mac-client",))
PROGRAMS = ("CameraCompanion", "PhotoSecretary")
MAC_COMMANDS = ("cq", "mq", "oq", "lq", "maintenance", "record-settings", "erase-records")
OBSERVED_READ_OPCODES = frozenset(("CQ", "MQ", "OQ", "LQ"))
REFERENCE_ACTION = "camera_companion_record_shooting_data_off_to_on_apply_once"
REFERENCE_APPROVAL_CONFIRMATION = (
    "I APPROVE ONE CAMERA COMPANION RECORD OFF-TO-ON APPLY ACTION"
)


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: Path
    data: bytes


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root is not an object: {path}")
    return value


def _write_new_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validate_session_id(value: str) -> str:
    if not SESSION_ID_RE.fullmatch(value):
        raise ValueError(
            "session ID must be 1-80 filename-safe ASCII characters and start "
            "with a letter or digit"
        )
    return value


def _validate_com(value: str) -> str:
    match = COM_RE.fullmatch(value)
    if not match or int(match.group(1)) > 65535:
        raise ValueError("guest COM must be canonical COM1 through COM65535")
    return value


def _validate_mode_arguments(args: argparse.Namespace) -> None:
    if args.mode in ("windows-direct", "mac-relay"):
        if not args.program or not args.guest_com:
            raise ValueError(f"{args.mode} requires --program and --guest-com")
        _validate_com(args.guest_com)
    elif args.program or args.guest_com:
        raise ValueError("--program/--guest-com belong only to Windows modes")

    if args.mode == "mac-relay":
        if not args.serial_port or not args.vm_pty:
            raise ValueError("mac-relay requires --serial-port and --vm-pty")
        if not SERIAL_RE.fullmatch(args.serial_port):
            raise ValueError("serial port must be an exact /dev/cu.* path")
        if not PTY_RE.fullmatch(args.vm_pty):
            raise ValueError("VM PTY must be an exact /dev/ttysN path")
    elif args.mode == "windows-direct" and args.vm_pty:
        raise ValueError("--vm-pty belongs only to mac-relay")
    elif args.mode == "windows-direct" and args.serial_port is not None:
        if not SERIAL_RE.fullmatch(args.serial_port):
            raise ValueError("windows-direct optional serial port must be /dev/cu.*")
    elif args.mode == "mac-client" and args.vm_pty:
        raise ValueError("--vm-pty belongs only to mac-relay")

    if args.mode == "mac-client":
        if not args.mac_command or not args.serial_port:
            raise ValueError("mac-client requires --mac-command and --serial-port")
        if args.mac_command not in MAC_COMMANDS:
            raise ValueError("orchestrated live Mac command must be cq, mq, oq, or lq")
        if not SERIAL_RE.fullmatch(args.serial_port):
            raise ValueError("serial port must be an exact /dev/cu.* path")
    elif args.mac_command:
        raise ValueError("--mac-command belongs only to mac-client")


def _q(value: Path | str) -> str:
    return shlex.quote(str(value))


def _powershell_literal(value: str) -> str:
    """Return one PowerShell single-quoted literal for preview-only commands."""
    return "'" + value.replace("'", "''") + "'"


def _commands(session_dir: Path, values: Dict[str, Any]) -> Dict[str, str]:
    connection_dir = Path(__file__).resolve().parent
    project_root = connection_dir.parent
    admission = connection_dir / "f100_usb_admission.py"
    relay = connection_dir / "f100_serial_relay.py"
    client = project_root / "mac-client" / "f100_readonly.py"
    admission_dir = session_dir / "mac-admission"
    result = {
        "snapshot_before": (
            f"python3 {_q(admission)} snapshot --output "
            f"{_q(admission_dir / 'before.json')}"
        ),
        "snapshot_after": (
            f"python3 {_q(admission)} snapshot --output "
            f"{_q(admission_dir / 'after.json')}"
        ),
        "policy_template": (
            f"python3 {_q(admission)} policy-template --output "
            f"{_q(admission_dir / 'policy.json')}"
        ),
        "evaluate_admission": (
            f"python3 {_q(admission)} evaluate "
            f"--before {_q(admission_dir / 'before.json')} "
            f"--after {_q(admission_dir / 'after.json')} "
            f"--policy {_q(admission_dir / 'policy.json')} "
            f"--output {_q(admission_dir / 'report.json')}"
        ),
    }

    mode = values["mode"]
    if mode in ("windows-direct", "mac-relay"):
        windows_root = (
            "C:\\F100Lab\\Logs\\F100LiveObserve\\" + values["session_id"]
        )
        result["windows_whatif"] = (
            "powershell.exe -NoProfile -ExecutionPolicy Bypass "
            "-File C:\\F100Lab\\Tools\\F100Capture\\"
            "Start-F100LiveObserve.ps1 "
            f"-Program {_powershell_literal(values['program'])} "
            f"-ComPort {_powershell_literal(values['guest_com'])} "
            f"-SessionRoot {_powershell_literal(windows_root)} "
            f"-IntegrationSessionId {_powershell_literal(values['session_id'])} "
            f"-CaptureBindingNonce {_powershell_literal(values['capture_binding_nonce'])} "
            "-AcknowledgeObserverDoesNotBlockWrites -WhatIf"
        )
    if mode == "mac-relay":
        result["relay_preview_only"] = (
            f"python3 {_q(relay)} live "
            f"--integration-session-id {_q(values['session_id'])} "
            f"--guest-com {_q(values['guest_com'])} "
            f"--serial-port {_q(values['serial_port'])} "
            f"--vm-pty {_q(values['vm_pty'])} "
            f"--admission-report {_q(admission_dir / 'report.json')} "
            f"--utm-forwarding-gate {_q(admission_dir / 'utm-forwarding-gate.json')} "
            f"--orchestration-plan {_q(session_dir / 'orchestration-plan.json')} "
            f"--capture-dir {_q(session_dir / 'mac-relay' / 'capture')} "
            "--max-seconds 120 --ack-observer-does-not-block-writes "
            "--ack-manual-admission-reviewed"
        )
    if mode == "mac-client":
        if values["mac_command"] == "maintenance":
            client = client.parent / "f100_maintenance.py"
        result["mac_client_preview_only"] = (
            f"python3 {_q(client)} --port {_q(values['serial_port'])} "
            f"--integration-session-id {_q(values['session_id'])} "
            f"--orchestration-plan {_q(session_dir / 'orchestration-plan.json')} "
            f"--admission-report {_q(admission_dir / 'report.json')} "
            f"--utm-forwarding-gate {_q(admission_dir / 'utm-forwarding-gate.json')} "
            f"--capture-dir {_q(session_dir / 'mac-client' / 'capture')} "
            + ("--execute-erase-and-detailed" if values["mac_command"] == "maintenance" else values["mac_command"])
            + (" --experimental-live" if values["mac_command"] == "lq" else "")
        )
    return result


def _populate_plan(args: argparse.Namespace, session_dir: Path) -> Path:
    for child in ("mac-admission", "windows-f100capture", "mac-relay", "mac-client"):
        (session_dir / child).mkdir(mode=0o700)

    values: Dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generated_utc": _utc_now(),
        "session_id": args.session_id,
        "mode": args.mode,
        "program": args.program,
        "guest_com": args.guest_com,
        "serial_port": args.serial_port,
        "vm_pty": args.vm_pty,
        "mac_command": args.mac_command,
        "capture_binding_nonce": secrets.token_hex(32),
        "physical_adapter_owner": {
            "windows-direct": "Windows USB pass-through",
            "mac-relay": "Mac relay",
            "mac-client": "Mac read-only client",
        }[args.mode],
        "execution_authorized": False,
        "orchestrator_opens_devices_or_launches_targets": False,
        "lq_default_live_blocked": True,
        "np_dp_ep_implemented": False,
        "hardware_validation": "NOT_PERFORMED",
        "live_safe_claim": False,
        "nikon_specification_match_claim": False,
        "boundaries": [
            "Exactly one owner may use the physical adapter in this session.",
            "Commands are previews; this plan does not authorize USB forwarding, Connect, Download, or camera I/O.",
            "The observer and relay do not prevent writes initiated by a target application.",
            "LQ live remains blocked by default; NP/DP/EP and write/delete/reset/time/rewind are outside scope.",
        ],
    }
    if args.mac_command == "maintenance":
        values.update(np_dp_ep_implemented=True, dp_implemented=False,
                      maintenance_action="erase-and-detailed", automatic_write_retry=False,
                      physical_adapter_owner="Mac maintenance client")
        values["boundaries"][-1] = "Explicit backup and confirmation required for EP then Detailed NP; DP and automatic write retry excluded."
    if args.mac_command in operations.NEW_SCOPES:
        operation = operations.descriptor(args.mac_command, getattr(args, "record_value", None))
        values.update(operation=operation, np_dp_ep_implemented=True, dp_implemented=False,
                      automatic_write_retry=False, candidate_live_blocked=False,
                      live_policy_revision=operations.LIVE_POLICY_REVISION,
                      physical_adapter_owner="Mac single-operation client")
        values["boundaries"][-1] = "One bound operation only. Backup and explicit confirmation required; NP also requires empty memory and operator-observed counter E. This plan does not execute or authorize I/O."
    values["commands"] = _commands(session_dir, values)
    if args.mac_command in operations.NEW_SCOPES:
        values["commands"]["mac_client_preview_only"] = "API ONLY: f100_record_operations.run with a freshly verified binding; no GUI or standalone CLI entry is connected."

    values["plan_sha256_without_this_field"] = _canonical_hash(values)
    plan_path = session_dir / "orchestration-plan.json"
    _write_new_json(plan_path, values)
    return plan_path


def create_plan(args: argparse.Namespace) -> Path:
    _validate_session_id(args.session_id)
    _validate_mode_arguments(args)
    if args.mac_command in operations.NEW_SCOPES:
        operations.descriptor(args.mac_command, getattr(args, "record_value", None))
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("--root must be an existing directory")
    session_dir = root / args.session_id
    if session_dir.exists() or session_dir.is_symlink():
        raise FileExistsError(f"refusing to reuse session directory: {session_dir}")
    session_dir.mkdir(mode=0o700)
    return _populate_plan(args, session_dir)


def populate_reserved_plan(args: argparse.Namespace) -> Path:
    """Populate a session reserved by the interactive assistant."""
    _validate_session_id(args.session_id)
    _validate_mode_arguments(args)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("--root must be an existing directory")
    session_dir = root / args.session_id
    transcript = session_dir / "terminal-transcript.txt"
    if session_dir.is_symlink() or not session_dir.is_dir():
        raise FileNotFoundError(f"reserved session directory is unavailable: {session_dir}")
    entries = {path.name for path in session_dir.iterdir()}
    if entries != {transcript.name} or transcript.is_symlink() or not transcript.is_file():
        raise FileExistsError(
            "reserved session is not an empty assistant transcript reservation: "
            + str(session_dir)
        )
    return _populate_plan(args, session_dir)


def _validate_self_hash(value: Dict[str, Any], field: str, label: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str):
        raise EvidenceError(f"{label} is missing {field}")
    copy = dict(value)
    del copy[field]
    if _canonical_hash(copy) != declared:
        raise EvidenceError(f"{label} self-hash mismatch")


def _validate_artifact(
    directory: Path,
    manifest: Dict[str, Any],
    file_field: str,
    bytes_field: str,
    hash_field: str,
) -> ArtifactSnapshot:
    name = manifest.get(file_field)
    if not isinstance(name, str) or Path(name).name != name:
        raise EvidenceError(f"invalid manifest filename field: {file_field}")
    try:
        root = directory.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"artifact directory unavailable: {directory}") from exc
    path = root / name
    if path.is_symlink():
        raise EvidenceError(f"artifact must not be a symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvidenceError(f"missing or unsafe artifact: {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceError(f"artifact is not a regular file: {path}")
        chunks: List[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(data) != manifest.get(bytes_field):
        raise EvidenceError(f"byte count mismatch: {path}")
    if hashlib.sha256(data).hexdigest() != manifest.get(hash_field):
        raise EvidenceError(f"SHA-256 mismatch: {path}")
    return ArtifactSnapshot(path=path, data=data)


def _parse_observed_requests(raw: bytes) -> Dict[str, int]:
    """Parse the complete captured host stream independently of API chunking."""

    offset = 0
    counts: Dict[str, int] = {}
    while offset < len(raw):
        if raw[offset] != 0:
            raise EvidenceError(
                f"Windows host stream has a byte outside a framed request at offset {offset}"
            )
        if len(raw) - offset < 5:
            raise EvidenceError("Windows host stream ends with a truncated request")
        opcode_bytes = raw[offset + 1 : offset + 3]
        if any(value < ord("A") or value > ord("Z") for value in opcode_bytes):
            raise EvidenceError("Windows host stream contains a malformed opcode")
        payload_length = int.from_bytes(raw[offset + 3 : offset + 5], "big")
        frame_end = offset + 5 + payload_length
        if frame_end > len(raw):
            raise EvidenceError("Windows host stream ends with a truncated payload")
        opcode = opcode_bytes.decode("ascii")
        counts[opcode] = counts.get(opcode, 0) + 1
        offset = frame_end
    return dict(sorted(counts.items()))


def _parse_observed_responses(raw: bytes) -> List[Tuple[int, bytes]]:
    offset = 0
    responses: List[Tuple[int, bytes]] = []
    while offset < len(raw):
        if len(raw) - offset < 3:
            raise EvidenceError("camera stream ends with a truncated response header")
        length = int.from_bytes(raw[offset : offset + 2], "big")
        if not (1 <= length <= 8192):
            raise EvidenceError("camera stream contains an invalid response length")
        end = offset + 2 + length
        if end > len(raw):
            raise EvidenceError("camera stream ends with a truncated response")
        responses.append((raw[offset + 2], raw[offset + 3 : end]))
        offset = end
    return responses


def record_reference_authorization(session_dir: Path, confirmation: str) -> Path:
    """Record, but never execute, one operator-approved reference UI exception."""

    session_dir = session_dir.expanduser().resolve()
    plan = _plan_from_session(session_dir)
    if plan["mode"] not in ("windows-direct", "mac-relay"):
        raise ValueError("reference application authorization requires a Windows mode")
    if plan.get("program") != "CameraCompanion":
        raise ValueError("the single reference action exception is CameraCompanion-only")
    if confirmation != REFERENCE_APPROVAL_CONFIRMATION:
        raise ValueError("exact reference action approval confirmation is required")
    record: Dict[str, Any] = {
        "schema": REFERENCE_AUTHORIZATION_SCHEMA,
        "generated_utc": _utc_now(),
        "session_id": plan["session_id"],
        "capture_binding_nonce": plan["capture_binding_nonce"],
        "program": "CameraCompanion",
        "action": REFERENCE_ACTION,
        "allowed_observed_outside_opcodes": {"NP": 2},
        "safety_policy_reference": "reverse-engineering/SAFETY_POLICY.md#2",
        "operator_explicit_approval_recorded": True,
        "orchestrator_execution_authorized": False,
        "observer_write_prevention_supported": False,
        "orchestration_plan_sha256": _sha256(
            session_dir / "orchestration-plan.json"
        ),
        "boundary": (
            "This pre-capture record binds observation of at most two NP requests "
            "to one approved Camera Companion UI Apply action. Timestamp ordering "
            "is evidence of sequencing, not cryptographic proof of operator timing. It does "
            "not authorize the Mac client, automatic execution, DP, or EP."
        ),
    }
    record["self_sha256_without_this_field"] = _canonical_hash(record)
    path = session_dir / "reference-action-authorization.json"
    _write_new_json(path, record)
    return path


def _validate_reference_action_authorization(
    session_dir: Path,
    plan: Dict[str, Any],
    opcode_counts: Dict[str, int],
    session_start: Dict[str, Any],
) -> str:
    outside = {
        opcode: count
        for opcode, count in opcode_counts.items()
        if opcode not in OBSERVED_READ_OPCODES
    }
    if not outside:
        return "NOT_REQUIRED"
    if outside != {"NP": outside.get("NP")} or outside.get("NP") not in (1, 2):
        raise EvidenceError(
            "observed reference action is outside the single approved NP exception"
        )
    path = session_dir / "reference-action-authorization.json"
    if not path.is_file():
        raise EvidenceError("observed NP has no bound reference action authorization")
    record = _load_json(path)
    if record.get("schema") != REFERENCE_AUTHORIZATION_SCHEMA:
        raise EvidenceError("reference action authorization schema mismatch")
    _validate_self_hash(
        record,
        "self_sha256_without_this_field",
        "reference action authorization",
    )
    expected = {
        "session_id": plan["session_id"],
        "capture_binding_nonce": plan["capture_binding_nonce"],
        "program": "CameraCompanion",
        "action": REFERENCE_ACTION,
        "allowed_observed_outside_opcodes": {"NP": 2},
        "safety_policy_reference": "reverse-engineering/SAFETY_POLICY.md#2",
        "operator_explicit_approval_recorded": True,
        "orchestrator_execution_authorized": False,
        "observer_write_prevention_supported": False,
        "orchestration_plan_sha256": _sha256(
            session_dir / "orchestration-plan.json"
        ),
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise EvidenceError(
                "reference action authorization binding mismatch: " + field
            )
    if plan.get("program") != "CameraCompanion":
        raise EvidenceError("NP exception cannot be bound to this reference program")
    if _parse_utc(record.get("generated_utc")) > _parse_utc(session_start.get("utc")):
        raise EvidenceError("reference action authorization was recorded after capture began")
    return "PRECAPTURE_AUTHORIZED_REFERENCE_OBSERVATION"


def _single_manifest(root: Path, schema: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    matches: List[Tuple[Path, Dict[str, Any]]] = []
    for path in sorted(root.rglob("session-manifest.json")):
        if path.is_symlink():
            raise EvidenceError(f"session manifest must not be a symlink: {path}")
        value = _load_json(path)
        if value.get("schema") == schema:
            matches.append((path, value))
    if len(matches) > 1:
        raise EvidenceError(f"multiple {schema} manifests under {root}")
    return matches[0] if matches else None


def _validate_admission(session_dir: Path) -> Tuple[Path, Dict[str, Any]]:
    directory = session_dir / "mac-admission"
    report_path = directory / "report.json"
    if not report_path.is_file():
        raise EvidenceError("missing mac-admission/report.json")
    report = _load_json(report_path)
    if report.get("schema") != ADMISSION_SCHEMA:
        raise EvidenceError("admission report schema mismatch")
    _validate_self_hash(report, "report_sha256_without_this_field", "admission report")
    if report.get("status") != "PASS" or report.get("violations") != []:
        raise EvidenceError("admission report is not a clean PASS")
    if report.get("manual_review_required_even_on_pass") is not True:
        raise EvidenceError("admission report lost its manual-review boundary")
    if report.get("safe_to_forward_automatically") is not False:
        raise EvidenceError("admission report improperly claims automatic forwarding safety")
    for filename, field in (
        ("before.json", "before_snapshot_sha256"),
        ("after.json", "after_snapshot_sha256"),
        ("policy.json", "policy_sha256"),
    ):
        path = directory / filename
        if not path.is_file():
            raise EvidenceError(f"missing admission input: {path}")
        if _canonical_hash(_load_json(path)) != report.get("inputs", {}).get(field):
            raise EvidenceError(f"admission input hash mismatch: {path}")
    return report_path, report


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise EvidenceError("admission report generated_utc is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("admission report generated_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise EvidenceError("admission report generated_utc has no timezone")
    return parsed.astimezone(timezone.utc)


def _require_fresh_admission(report: Dict[str, Any], max_age_seconds: int = 900) -> None:
    age = (datetime.now(timezone.utc) - _parse_utc(report.get("generated_utc"))).total_seconds()
    if age < -60 or age > max_age_seconds:
        raise EvidenceError("admission report is not fresh enough for a live next step")


def _session_start_event(events_data: bytes) -> Dict[str, Any]:
    try:
        for line in events_data.decode("utf-8").splitlines():
            value = json.loads(line)
            if isinstance(value, dict) and value.get("event") == "session_start":
                return value
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot inspect Windows session_start event: {exc}") from exc
    raise EvidenceError("Windows events do not contain session_start")


def _validate_windows(
    session_dir: Path, plan: Dict[str, Any]
) -> Tuple[Path, Dict[str, Any], ArtifactSnapshot, ArtifactSnapshot, Dict[str, int], Dict[str, Any]]:
    report = _load_json(session_dir / "mac-admission/report.json")
    serial_paths = report.get("delta", {}).get("new_serial_paths")
    if not isinstance(serial_paths, list) or len(serial_paths) != 1:
        raise EvidenceError("Windows admission must identify exactly one serial port")
    bound_serial_port = plan.get("serial_port") or serial_paths[0]
    try:
        live_binding.validate_live_binding(
            orchestration_plan=session_dir / "orchestration-plan.json",
            admission_report=session_dir / "mac-admission/report.json",
            forwarding_gate=session_dir / "mac-admission/utm-forwarding-gate.json",
            integration_session_id=plan["session_id"],
            serial_port=bound_serial_port,
            expected_mode=plan["mode"],
            expected_guest_com=plan["guest_com"],
            require_freshness=False,
        )
    except live_binding.BindingError as exc:
        raise EvidenceError("Windows final live binding failed: " + str(exc)) from exc
    found = _single_manifest(session_dir / "windows-f100capture", WINDOWS_SCHEMA)
    if not found:
        raise EvidenceError("missing Windows F100Capture session manifest")
    path, manifest = found
    if manifest.get("observation_profile") != "live-com-observe":
        raise EvidenceError("Windows observation profile is not live-com-observe")
    expected_com = "\\\\.\\" + plan["guest_com"]
    if manifest.get("canonical_com_target") != expected_com:
        raise EvidenceError("Windows canonical COM target does not match the plan")
    if manifest.get("non_prevention_acknowledgement_present") is not True:
        raise EvidenceError("Windows non-prevention acknowledgement is missing")
    for field, expected in (
        ("target_hash_match", True),
        ("required_file_hashes_match", True),
        ("event_stream_integrity_status", "complete"),
        ("selected_com_open_observed", True),
        ("byte_reconstruction_complete", True),
        ("frame_annotation_complete", True),
        ("serial_configuration_status", "observed_success"),
        ("capture_closed_cleanly", True),
        ("live_capture_purpose_status", "serial_io_observed_unvalidated_not_acceptance"),
    ):
        if manifest.get(field) != expected:
            raise EvidenceError(f"Windows completion field is not acceptable: {field}")
    tx = _validate_artifact(
        path.parent,
        manifest,
        "host_to_camera_file",
        "host_to_camera_bytes",
        "host_to_camera_sha256",
    )
    rx = _validate_artifact(
        path.parent,
        manifest,
        "camera_to_host_file",
        "camera_to_host_bytes",
        "camera_to_host_sha256",
    )
    events = _validate_artifact(
        path.parent, manifest, "events_file", "events_bytes", "events_sha256"
    )
    session_start = _session_start_event(events.data)
    if session_start.get("target_label") != plan["program"]:
        raise EvidenceError("Windows target label does not match the plan")
    if session_start.get("integration_session_id") != plan["session_id"]:
        raise EvidenceError("Windows capture session ID does not match the plan")
    if session_start.get("capture_binding_nonce") != plan["capture_binding_nonce"]:
        raise EvidenceError("Windows capture binding nonce does not match the plan")
    opcode_counts = _parse_observed_requests(tx.data)
    response_count = len(_parse_observed_responses(rx.data))
    request_count = sum(opcode_counts.values())
    if request_count == 0 or response_count != request_count:
        raise EvidenceError("Windows request/response transaction count is incomplete")
    outside_count = sum(
        count
        for opcode, count in opcode_counts.items()
        if opcode not in OBSERVED_READ_OPCODES
    )
    if manifest.get("observed_opcode_outside_cq_mq_oq_lq_events") != outside_count:
        raise EvidenceError(
            "Windows outside-opcode count disagrees with the captured host stream"
        )
    return path, manifest, tx, rx, opcode_counts, session_start


def _validate_relay(
    session_dir: Path,
    plan: Dict[str, Any],
    admission_path: Path,
    windows_tx: ArtifactSnapshot,
    windows_rx: ArtifactSnapshot,
) -> Tuple[Path, Dict[str, Any]]:
    found = _single_manifest(session_dir / "mac-relay", RELAY_SCHEMA)
    if not found:
        raise EvidenceError("missing Mac relay session manifest")
    path, manifest = found
    integration = manifest.get("integration", {})
    if not isinstance(integration, dict):
        raise EvidenceError("relay live evidence binding is malformed")
    try:
        expected_binding = live_binding.validate_live_binding(
            orchestration_plan=session_dir / "orchestration-plan.json",
            admission_report=admission_path,
            forwarding_gate=session_dir / "mac-admission/utm-forwarding-gate.json",
            integration_session_id=plan["session_id"],
            serial_port=plan["serial_port"],
            expected_mode="mac-relay",
            expected_guest_com=plan["guest_com"],
            require_freshness=False,
        )
    except live_binding.BindingError as exc:
        raise EvidenceError("relay live evidence binding failed: " + str(exc)) from exc
    for key, expected in expected_binding.items():
        if integration.get(key) != expected:
            raise EvidenceError("relay manifest binding mismatch: " + key)
    if integration.get("session_id") != plan["session_id"]:
        raise EvidenceError("relay session ID does not match the plan")
    if integration.get("guest_com") != plan["guest_com"]:
        raise EvidenceError("relay guest COM does not match the plan")
    if integration.get("admission_report_sha256") != _sha256(admission_path):
        raise EvidenceError("relay admission report file hash does not match")
    if manifest.get("mode") != "live-pty-relay-unvalidated":
        raise EvidenceError("relay evidence is not from live PTY relay mode")
    if manifest.get("outcome") != "success":
        raise EvidenceError("relay did not finish successfully")
    if manifest.get("relay_byte_reconstruction_complete") is not True:
        raise EvidenceError("relay byte reconstruction is incomplete")
    endpoints = manifest.get("endpoints", {})
    if endpoints.get("serial_port") != plan["serial_port"]:
        raise EvidenceError("relay serial endpoint does not match the plan")
    if endpoints.get("vm_pty") != plan["vm_pty"]:
        raise EvidenceError("relay VM PTY does not match the plan")
    relay_tx = _validate_artifact(
        path.parent,
        manifest,
        "vm_to_serial_file",
        "vm_to_serial_bytes",
        "vm_to_serial_sha256",
    )
    relay_rx = _validate_artifact(
        path.parent,
        manifest,
        "serial_to_vm_file",
        "serial_to_vm_bytes",
        "serial_to_vm_sha256",
    )
    _validate_artifact(
        path.parent, manifest, "events_file", "events_bytes", "events_sha256"
    )
    if windows_tx.data != relay_tx.data:
        raise EvidenceError("Windows TX and relay VM-to-serial byte streams differ")
    if windows_rx.data != relay_rx.data:
        raise EvidenceError("Windows RX and relay serial-to-VM byte streams differ")
    return path, manifest


def _validate_mac_client(
    session_dir: Path, plan: Dict[str, Any]
) -> Tuple[Path, Dict[str, Any]]:
    found = _single_manifest(session_dir / "mac-client", MAC_CLIENT_SCHEMA)
    if not found:
        raise EvidenceError("missing Mac client session manifest")
    path, manifest = found
    integration = manifest.get("integration", {})
    if not isinstance(integration, dict):
        raise EvidenceError("Mac client live evidence binding is malformed")
    try:
        expected_binding = live_binding.validate_live_binding(
            orchestration_plan=session_dir / "orchestration-plan.json",
            admission_report=session_dir / "mac-admission/report.json",
            forwarding_gate=session_dir / "mac-admission/utm-forwarding-gate.json",
            integration_session_id=plan["session_id"],
            serial_port=plan["serial_port"],
            expected_mode="mac-client",
            expected_command=plan["mac_command"],
            require_freshness=False,
        )
    except live_binding.BindingError as exc:
        raise EvidenceError("Mac client live evidence binding failed: " + str(exc)) from exc
    for key, expected in expected_binding.items():
        if integration.get(key) != expected:
            raise EvidenceError("Mac client manifest binding mismatch: " + key)
    if manifest.get("command") != plan["mac_command"]:
        raise EvidenceError("Mac client command does not match the plan")
    if manifest.get("port") != plan["serial_port"]:
        raise EvidenceError("Mac client serial port does not match the plan")
    if plan.get("mac_command") in operations.NEW_SCOPES:
        raise EvidenceError("single-operation capture requires explicit operation review; read-only acceptance is inapplicable")
    if plan.get("mac_command") == "maintenance":
        raise EvidenceError("maintenance capture requires explicit operation review; read-only acceptance is inapplicable")
    if manifest.get("np_dp_ep_implemented") is not False:
        raise EvidenceError("Mac client manifest does not preserve the NP/DP/EP boundary")
    if manifest.get("lq_default_live_blocked") is not True:
        raise EvidenceError("Mac client manifest does not preserve the LQ boundary")
    if manifest.get("outcome") != "success":
        raise EvidenceError("Mac client did not finish successfully")
    if manifest.get("api_byte_reconstruction_complete") is not True:
        raise EvidenceError("Mac client byte reconstruction is incomplete")
    tx = _validate_artifact(
        path.parent,
        manifest,
        "host_to_camera_file",
        "host_to_camera_bytes",
        "host_to_camera_sha256",
    )
    rx = _validate_artifact(
        path.parent,
        manifest,
        "camera_to_host_file",
        "camera_to_host_bytes",
        "camera_to_host_sha256",
    )
    _validate_artifact(
        path.parent, manifest, "events_file", "events_bytes", "events_sha256"
    )
    command = plan["mac_command"].upper()
    sequence = ["MQ", "OQ", "LQ"] if command == "LQ" else [command]
    responses = _parse_observed_responses(rx.data)
    remaining_tx = tx.data
    cursor = 0
    for opcode in sequence:
        for attempt in range(2):
            expected_tx = b"\x00" + opcode.encode("ascii") + b"\x00\x00"
            if not remaining_tx.startswith(expected_tx) or cursor >= len(responses):
                raise EvidenceError("Mac client TX/RX does not match planned read sequence")
            remaining_tx = remaining_tx[len(expected_tx):]
            status, payload = responses[cursor]
            cursor += 1
            if status == 0x79 and not payload and attempt == 0:
                continue
            if status != 0x61:
                raise EvidenceError("Mac client read did not finish successfully")
            expected_length = {"CQ": 4, "MQ": 1, "OQ": 2}.get(opcode)
            if expected_length is not None and len(payload) != expected_length:
                raise EvidenceError("Mac client response length does not match planned command")
            if opcode == "LQ" and (not payload or payload[0] not in (0, 1)):
                raise EvidenceError("Mac client LQ payload is missing or malformed")
            break
        else:
            raise EvidenceError("Mac client retry budget exhausted")
    if remaining_tx or cursor != len(responses):
        raise EvidenceError("Mac client captured unexpected extra traffic")
    return path, manifest


def _validate_ownership_isolation(session_dir: Path, mode: str) -> None:
    allowed = {
        "windows-direct": {"windows-f100capture"},
        "mac-relay": {"windows-f100capture", "mac-relay"},
        "mac-client": {"mac-client"},
    }[mode]
    roots = {
        "windows-f100capture": WINDOWS_SCHEMA,
        "mac-relay": RELAY_SCHEMA,
        "mac-client": MAC_CLIENT_SCHEMA,
    }
    for name, schema in roots.items():
        if name not in allowed and _single_manifest(session_dir / name, schema):
            raise EvidenceError(
                f"physical-owner conflict: {name} evidence is forbidden in {mode} mode"
            )


def _plan_from_session(session_dir: Path) -> Dict[str, Any]:
    plan = _load_json(session_dir / "orchestration-plan.json")
    if plan.get("schema") != PLAN_SCHEMA:
        raise EvidenceError("orchestration plan schema mismatch")
    _validate_self_hash(plan, "plan_sha256_without_this_field", "orchestration plan")
    _validate_session_id(str(plan.get("session_id", "")))
    if session_dir.name != plan["session_id"]:
        raise EvidenceError("session directory name does not match the plan")
    if plan.get("mode") not in MODES:
        raise EvidenceError("unknown orchestration mode")
    if plan.get("execution_authorized") is not False:
        raise EvidenceError("plan improperly claims execution authorization")
    return plan


def inspect_session(session_dir: Path) -> Dict[str, Any]:
    session_dir = session_dir.expanduser().resolve()
    plan = _plan_from_session(session_dir)
    checks: List[Dict[str, str]] = []
    errors: List[str] = []
    evidence_errors: List[str] = []
    authorization_errors: List[str] = []

    def run_check(name: str, function: Any, *, authorization: bool = False) -> Any:
        try:
            result = function()
            checks.append({"name": name, "status": "PASS"})
            return result
        except EvidenceError as exc:
            checks.append({"name": name, "status": "INCOMPLETE_OR_FAIL"})
            message = str(exc)
            errors.append(message)
            (authorization_errors if authorization else evidence_errors).append(message)
            return None

    admission = run_check("mac_admission", lambda: _validate_admission(session_dir))
    run_check(
        "physical_owner_isolation",
        lambda: _validate_ownership_isolation(session_dir, plan["mode"]),
    )
    windows = None
    if plan["mode"] in ("windows-direct", "mac-relay"):
        windows = run_check(
            "windows_f100capture", lambda: _validate_windows(session_dir, plan)
        )
        if windows:
            authorization_status = run_check(
                "reference_action_authorization",
                lambda: _validate_reference_action_authorization(
                    session_dir, plan, windows[4], windows[5]
                ),
                authorization=True,
            )
            if authorization_status == "NOT_REQUIRED":
                checks[-1]["status"] = "NOT_REQUIRED"
        else:
            authorization_status = "BLOCKED"
            checks.append(
                {"name": "reference_action_authorization", "status": "BLOCKED"}
            )
    if plan["mode"] == "mac-relay":
        if admission and windows:
            run_check(
                "relay_crosscheck",
                lambda: _validate_relay(
                    session_dir,
                    plan,
                    admission[0],
                    windows[2],
                    windows[3],
                ),
            )
        else:
            checks.append({"name": "relay_crosscheck", "status": "BLOCKED"})
            errors.append("relay cross-check requires valid admission and Windows evidence")
    if plan["mode"] == "mac-client":
        run_check("mac_client", lambda: _validate_mac_client(session_dir, plan))

    complete = not errors
    if plan["mode"] == "mac-client":
        authorization_status = "NOT_APPLICABLE"
    elif windows and not authorization_errors:
        authorization_status = (
            "NOT_REQUIRED"
            if not any(
                opcode not in OBSERVED_READ_OPCODES for opcode in windows[4]
            )
            else "PRECAPTURE_AUTHORIZED_REFERENCE_OBSERVATION"
        )
    elif windows:
        authorization_status = "UNAUTHORIZED_OR_UNVERIFIED"
    return {
        "schema": REPORT_SCHEMA,
        "generated_utc": _utc_now(),
        "session_id": plan["session_id"],
        "mode": plan["mode"],
        "status": "PASS" if complete else "INCOMPLETE_OR_FAIL",
        "checks": checks,
        "errors": errors,
        "evidence_integrity_status": (
            "PASS" if not evidence_errors else "INCOMPLETE_OR_FAIL"
        ),
        "action_authorization_status": authorization_status,
        "evidence_errors": evidence_errors,
        "authorization_errors": authorization_errors,
        "observed_request_opcode_counts": windows[4] if windows else {},
        "hardware_validation": "NOT_ESTABLISHED_BY_ORCHESTRATION",
        "live_safe_claim": False,
        "nikon_specification_match_claim": False,
        "evidence_boundary": (
            "PASS establishes local manifest, file-hash, session-correlation, and "
            "mode-specific byte-stream consistency only."
        ),
    }


def _next_step(session_dir: Path, plan: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    admission = session_dir / "mac-admission"
    commands = plan["commands"]
    for filename, key, label in (
        ("before.json", "snapshot_before", "capture the disconnected baseline"),
        ("after.json", "snapshot_after", "after explicit approval, connect only the adapter and capture the delta"),
        ("policy.json", "policy_template", "create and manually edit the deny-by-default policy"),
        ("report.json", "evaluate_admission", "evaluate the reviewed admission evidence"),
    ):
        if not (admission / filename).exists():
            return label, commands[key]
    try:
        _, report = _validate_admission(session_dir)
        _require_fresh_admission(report)
    except EvidenceError as exc:
        return "blocked: repair or re-run admission evidence: " + str(exc), None

    if plan["mode"] in ("windows-direct", "mac-relay"):
        if not _single_manifest(session_dir / "windows-f100capture", WINDOWS_SCHEMA):
            return (
                "run the Windows hash/launch preview; actual launch and UI actions need separate approval",
                commands["windows_whatif"],
            )
    if plan["mode"] == "mac-relay":
        if not _single_manifest(session_dir / "mac-relay", RELAY_SCHEMA):
            return (
                "relay command preview only; execution needs separate approval",
                commands["relay_preview_only"],
            )
    if plan["mode"] == "mac-client":
        if not _single_manifest(session_dir / "mac-client", MAC_CLIENT_SCHEMA):
            return (
                "Mac client command preview only; execution needs separate approval",
                commands["mac_client_preview_only"],
            )
    return "verify the completed evidence bundle", None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="F100 evidence orchestrator (plans and verifies; never executes live I/O)"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    init = sub.add_parser("init", help="create a new, non-executing session plan")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--session-id", required=True)
    init.add_argument("--mode", choices=MODES, required=True)
    init.add_argument("--program", choices=PROGRAMS)
    init.add_argument("--guest-com")
    init.add_argument("--serial-port")
    init.add_argument("--vm-pty")
    init.add_argument("--mac-command", choices=MAC_COMMANDS)
    init.add_argument("--record-value", choices=sorted(operations.NP_VALUES))

    status = sub.add_parser("status", help="show the next non-automatic step")
    status.add_argument("--session", type=Path, required=True)

    verify = sub.add_parser("verify", help="verify correlation and artifact integrity")
    verify.add_argument("--session", type=Path, required=True)
    verify.add_argument("--output", type=Path)

    if "windows-direct" in MODES:
        authorize = sub.add_parser(
            "record-reference-authorization",
            help="record explicit approval for the single SAFETY_POLICY section 2 exception",
        )
        authorize.add_argument("--session", type=Path, required=True)
        authorize.add_argument("--confirm-exact-scope", required=True)

    args = parser.parse_args()
    try:
        if args.action == "init":
            path = create_plan(args)
            print(path)
            print("ExecutionAuthorized=false")
            return 0
        if args.action == "record-reference-authorization":
            path = record_reference_authorization(
                args.session, args.confirm_exact_scope
            )
            print(path)
            print("OrchestratorExecutionAuthorized=false")
            return 0
        session = args.session.expanduser().resolve()
        plan = _plan_from_session(session)
        if args.action == "status":
            label, command = _next_step(session, plan)
            print("Session=" + plan["session_id"])
            print("Mode=" + plan["mode"])
            print("Next=" + label)
            if command:
                print("CommandPreview=" + command)
            print("ExecutionAuthorized=false")
            return 0
        report = inspect_session(session)
        if args.output:
            _write_new_json(args.output.expanduser().resolve(), report)
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 3
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
