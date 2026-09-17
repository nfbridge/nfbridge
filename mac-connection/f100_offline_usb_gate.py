#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline, supervised Mac-side USB admission gate for the F100 cable.

The intended baseline is: network isolated, existing USB state stable, candidate
cable/adapter disconnected, and F100 disconnected.  This tool records a
before/after logical-enumeration delta and can produce a short-lived gate for
manual UTM forwarding.  It never controls UTM or opens a serial device.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import f100_usb_admission as admission


SESSION_SCHEMA = "f100-offline-usb-discovery/0.2"
NETWORK_SCHEMA = "f100-offline-network-gate/0.5"
SUMMARY_SCHEMA = "f100-offline-usb-discovery-summary/0.2"
APPROVAL_SCHEMA = "f100-offline-usb-manual-approval/0.1"
GATE_SCHEMA = "f100-offline-utm-forwarding-gate/0.2"
PREAUTH_SUMMARY_SCHEMA = "f100-usb-preauth-summary/0.3"

HEX_ID_RE = re.compile(r"^(?:0x)?([0-9a-fA-F]{4})$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
SERIAL_RE = re.compile(r"^/dev/cu\.[A-Za-z0-9._-]+$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BINDING_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
INTERFACE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
INTERFACE_HEADER_LINE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9._-]*:.*$", re.MULTILINE
)
INTERFACE_HEADER_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9._-]*):\s+"
    r"flags=(?P<mask>[0-9A-Fa-f]+)<(?P<flags>[^>]*)>[^\n]*$"
)
INTERFACE_FLAG_BITS = {
    "UP": 0x0001,
    "BROADCAST": 0x0002,
    "DEBUG": 0x0004,
    "LOOPBACK": 0x0008,
    "POINTOPOINT": 0x0010,
    "SMART": 0x0020,
    "NOTRAILERS": 0x0020,
    "RUNNING": 0x0040,
    "NOARP": 0x0080,
    "PROMISC": 0x0100,
    "ALLMULTI": 0x0200,
    "OACTIVE": 0x0400,
    "SIMPLEX": 0x0800,
    "LINK0": 0x1000,
    "LINK1": 0x2000,
    "LINK2": 0x4000,
    "ALTPHYS": 0x4000,
    "MULTICAST": 0x8000,
    "CANTCONFIG": 0x10000,
    "PPROMISC": 0x20000,
    "MONITOR": 0x40000,
    "STATICARP": 0x80000,
    "DYING": 0x200000,
    "RENAMING": 0x400000,
}
ROUTE_ABSENT_RE = re.compile(
    r"route:\s+writing to routing socket:\s+not in table", re.IGNORECASE
)

CHECKLIST = """F100 cable Mac-side admission checklist

PREPARE
[ ] Mac network is isolated before this program starts.
[ ] macOS 'Allow accessories to connect' is set to 'Always Ask'.
[ ] Existing USB accessories are stable; the candidate cable is disconnected.
[ ] Nikon F100 is powered off and physically disconnected from the cable.
[ ] No unrelated USB device will be attached or removed during the run.

DISCOVERY
[ ] Complete f100_preauth_gate.py first when using the full first-use workflow.
[ ] Only AUTH_REQUEST_OBSERVED or inconclusive NO_ENUMERATION may proceed to
    cable-only post-authorization discovery; PREAUTH_ANOMALY is a hard stop.
[ ] Run this CLI, let it capture the existing baseline, then connect only the
    candidate cable/USB adapter when prompted.
[ ] Approve the macOS accessory prompt only for this deliberate connection.
[ ] Do not connect the F100 and do not open the new /dev/cu.* path.
[ ] Review VID/PID, product/manufacturer, topology, fingerprint and serial path.
[ ] Any new HID, disk, network interface, extension, extra USB identity or
    incomplete snapshot is a hard stop.

FORWARDING
[ ] Run approve with the full displayed fingerprint and exact /dev/cu.* path.
[ ] Run gate within 15 minutes while the Mac remains network-isolated.
[ ] A gate PASS is only permission to consider manual UTM forwarding; it does
    not authenticate firmware, block BadUSB, prove electrical safety, or permit
    F100/Connect/Download/camera I/O.
"""


class GateError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_binding(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()


def _decode_json_payload(payload: bytes, path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON root is not an object: {path}")
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON root is not an object: {path}")
    return value


def _write_new(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError("refusing to overwrite evidence: " + str(path))
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _normalize_hex_id(value: str) -> str:
    match = HEX_ID_RE.fullmatch(value)
    if not match:
        raise ValueError("VID/PID must be exactly four hexadecimal digits")
    return "0x" + match.group(1).lower()


def _run(command: Sequence[str], timeout: float = 20.0) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "exit_code": None, "stdout": b"", "stderr": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr.decode("utf-8", "replace"),
    }


def _command_record(result: Dict[str, Any]) -> Dict[str, Any]:
    output = result.get("stdout", b"")
    if not isinstance(output, bytes):
        raise GateError("network runner stdout must be bytes")
    return {
        "ok": bool(result.get("ok")),
        "exit_code": result.get("exit_code"),
        "stdout_bytes": len(output),
        "stdout_sha256": hashlib.sha256(output).hexdigest(),
        "stdout_text": output.decode("utf-8", "replace"),
        "stderr": str(result.get("stderr", "")),
    }


def _command_succeeded(result: Dict[str, Any]) -> bool:
    return result.get("ok") is True and result.get("exit_code") == 0


def _default_route_state(result: Dict[str, Any]) -> str:
    """Return present, absent, or unknown for macOS route(8) output.

    On current macOS releases, ``route -n get default`` can exit successfully
    while writing ``not in table`` to stderr and leaving stdout empty.  Exit
    status alone therefore cannot distinguish an existing route from an absent
    one.  Unexpected empty/error output remains fail-closed as ``unknown``.
    """
    output = result.get("stdout", b"")
    if not isinstance(output, bytes):
        raise GateError("network runner stdout must be bytes")
    stderr = str(result.get("stderr", "")).strip()
    if not _command_succeeded(result):
        return "unknown"
    if output.strip():
        return "present"
    if ROUTE_ABSENT_RE.fullmatch(stderr):
        return "absent"
    return "unknown"


def _interface_state(name: str, text: str) -> str:
    """Return active, inactive, or indeterminate for one ifconfig record."""
    header_lines = INTERFACE_HEADER_LINE_RE.findall(text)
    if len(header_lines) != 1:
        return "indeterminate"
    header = INTERFACE_HEADER_RE.fullmatch(header_lines[0])
    if header is None or header.group("name") != name:
        return "indeterminate"

    raw_flags = header.group("flags")
    flags = [] if not raw_flags else [item.strip() for item in raw_flags.split(",")]
    if any(not item for item in flags) or len(flags) != len(set(flags)):
        return "indeterminate"
    if any(item not in INTERFACE_FLAG_BITS for item in flags):
        return "indeterminate"

    mask = int(header.group("mask"), 16)
    represented_mask = 0
    for flag in flags:
        represented_mask |= INTERFACE_FLAG_BITS[flag]
    if represented_mask != mask:
        return "indeterminate"

    status_lines = re.findall(r"^\s*status\b[^\n]*$", text, re.MULTILINE)
    if len(status_lines) > 1:
        return "indeterminate"
    status: Optional[str] = None
    if status_lines:
        status_match = re.fullmatch(
            r"\s*status:\s*(active|inactive)\s*",
            status_lines[0],
        )
        if status_match is None:
            return "indeterminate"
        status = status_match.group(1)

    # Validate every reported address before accepting even an explicitly
    # inactive interface.  Administrative/media state must not turn malformed
    # ifconfig output into evidence for an offline PASS.
    address_lines = re.findall(r"^\s*inet[^\n]*$", text, re.MULTILINE)
    addresses = []
    for line in address_lines:
        match = re.fullmatch(r"\s*(inet|inet6)\s+(\S+)(.*)", line)
        if match is None:
            return "indeterminate"
        family = match.group(1)
        tokens = [match.group(2)]
        remainder = match.group(3)
        if "-->" in remainder:
            peer = re.search(r"(?:^|\s)-->(?:\s+)(\S+)", remainder)
            if peer is None:
                return "indeterminate"
            tokens.append(peer.group(1))
        for token in tokens:
            if token.count("%") > 1:
                return "indeterminate"
            literal, separator, zone = token.partition("%")
            if family == "inet":
                if separator:
                    return "indeterminate"
            elif separator and (
                not INTERFACE_NAME_RE.fullmatch(zone) or zone != name
            ):
                return "indeterminate"
            try:
                address = ipaddress.ip_address(literal)
            except ValueError:
                return "indeterminate"
            if (family == "inet" and address.version != 4) or (
                family == "inet6" and address.version != 6
            ):
                return "indeterminate"
            addresses.append(address)

    flags_active = bool(set(flags).intersection({"UP", "RUNNING"}))
    if status == "active":
        return "active" if flags_active else "indeterminate"
    if status == "inactive":
        # macOS commonly retains UP/RUNNING administrative flags while the
        # physical media status is explicitly inactive (including Wi-Fi Off).
        return "inactive"
    if not flags_active:
        return "inactive"

    # utun/llw/awdl interfaces can remain administratively UP after their
    # underlay is gone. With both default routes absent (checked by the caller),
    # no explicit active media status, and no address beyond link-local, treat
    # those known macOS virtual interfaces as dormant. A Tailscale/VPN address,
    # other non-link-local address, or an unfamiliar UP interface still fails.
    if re.fullmatch(r"(?:utun|llw|awdl)[0-9]+", name) and all(
        address.is_link_local for address in addresses
    ):
        return "inactive"
    return "active"


def _wifi_devices(text: str) -> Tuple[List[str], List[str]]:
    """Parse exactly one unambiguous Wi-Fi hardware-port block."""
    violations: List[str] = []
    lines = text.splitlines()
    port_header_lines = [line for line in lines if re.match(r"^Hardware Port\b", line)]
    if any(
        re.fullmatch(r"Hardware Port:\s*.+", line) is None
        for line in port_header_lines
    ):
        violations.append("network hardware-port output has a malformed port header")
        return [], violations
    port_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"Hardware Port:\s*.+", line)
    ]
    wifi_blocks: List[List[str]] = []
    for position, start in enumerate(port_indexes):
        end = port_indexes[position + 1] if position + 1 < len(port_indexes) else len(lines)
        block = lines[start:end]
        if re.fullmatch(r"Hardware Port:\s*(?:Wi-Fi|AirPort)\s*", block[0]):
            wifi_blocks.append(block)

    if len(wifi_blocks) != 1:
        violations.append(
            "network hardware-port output must contain exactly one Wi-Fi port block"
        )
        return [], violations

    device_lines = [
        line for line in wifi_blocks[0] if re.match(r"^\s*Device\b", line)
    ]
    if len(device_lines) != 1:
        violations.append(
            "Wi-Fi hardware port must contain exactly one device declaration"
        )
        return [], violations
    match = re.fullmatch(r"Device:\s*([A-Za-z][A-Za-z0-9._-]*)\s*", device_lines[0])
    if match is None:
        violations.append("Wi-Fi hardware port has no valid device name")
        return [], violations
    return [match.group(1)], violations


def collect_network_gate(
    *, runner: Callable[[Sequence[str]], Dict[str, Any]] = _run
) -> Dict[str, Any]:
    route4 = runner(["/sbin/route", "-n", "get", "default"])
    route6 = runner(["/sbin/route", "-n", "get", "-inet6", "default"])
    interfaces = runner(["/sbin/ifconfig", "-l"])
    hardware = runner(["/usr/sbin/networksetup", "-listallhardwareports"])
    records = {
        "default_ipv4": _command_record(route4),
        "default_ipv6": _command_record(route6),
        "interface_list": _command_record(interfaces),
        "hardware_ports": _command_record(hardware),
    }
    violations: List[str] = []
    route4_state = _default_route_state(route4)
    route6_state = _default_route_state(route6)
    if route4_state == "present":
        violations.append("IPv4 default route is present")
    elif route4_state == "unknown":
        violations.append("cannot determine whether an IPv4 default route is present")
    if route6_state == "present":
        violations.append("IPv6 default route is present")
    elif route6_state == "unknown":
        violations.append("cannot determine whether an IPv6 default route is present")
    invalid_names: List[str] = []
    if not _command_succeeded(interfaces):
        violations.append("cannot enumerate network interfaces")
        names: List[str] = []
    else:
        raw_names = interfaces["stdout"].decode("utf-8", "replace").split()
        invalid_names = [
            name for name in raw_names if not INTERFACE_NAME_RE.fullmatch(name)
        ]
        names = [name for name in raw_names if INTERFACE_NAME_RE.fullmatch(name)]
        if not raw_names:
            violations.append("network interface list is empty")
        if invalid_names:
            violations.append(
                "network interface list contains malformed names: "
                + ", ".join(invalid_names)
            )
        if len(names) != len(set(names)):
            violations.append("network interface list contains duplicate names")
        names = list(dict.fromkeys(names))
        if "lo0" not in names:
            violations.append("network interface list does not contain lo0")

    active: List[str] = []
    inactive: List[str] = []
    indeterminate: List[str] = []
    addressed: List[str] = []
    for name in names:
        if name == "lo0":
            continue
        state = runner(["/sbin/ifconfig", name])
        records["interface_" + name] = _command_record(state)
        if not _command_succeeded(state):
            violations.append("cannot inspect interface: " + name)
            indeterminate.append(name)
            continue
        text = state["stdout"].decode("utf-8", "replace")
        if re.search(r"^\s*inet6?\s+", text, re.MULTILINE):
            addressed.append(name)
        interface_state = _interface_state(name, text)
        if interface_state == "indeterminate":
            indeterminate.append(name)
        elif interface_state == "active":
            active.append(name)
        else:
            inactive.append(name)
    if active:
        violations.append("non-loopback active interfaces: " + ", ".join(active))
    if indeterminate:
        violations.append(
            "cannot classify non-loopback interfaces: "
            + ", ".join(indeterminate)
        )

    wifi_devices: List[str] = []
    if not _command_succeeded(hardware):
        violations.append("cannot enumerate network hardware ports")
    else:
        text = hardware["stdout"].decode("utf-8", "replace")
        if not text.strip():
            violations.append("network hardware-port output is empty")
        else:
            wifi_devices, wifi_violations = _wifi_devices(text)
            violations.extend(wifi_violations)
    for device in wifi_devices:
        power = runner(["/usr/sbin/networksetup", "-getairportpower", device])
        records["wifi_power_" + device] = _command_record(power)
        text = power.get("stdout", b"").decode("utf-8", "replace")
        expected = re.compile(
            r"Wi-Fi Power \(" + re.escape(device) + r"\):\s*Off"
        )
        if not _command_succeeded(power) or not expected.fullmatch(text.strip()):
            violations.append("Wi-Fi power is not confirmed off: " + device)

    return {
        "schema": NETWORK_SCHEMA,
        "generated_utc": _utc_now(),
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "default_route_states": {
            "ipv4": route4_state,
            "ipv6": route6_state,
        },
        "active_interfaces": active,
        "inactive_interfaces": inactive,
        "indeterminate_interfaces": indeterminate,
        "addressed_interfaces": addressed,
        "invalid_interface_names": invalid_names,
        "wifi_devices": wifi_devices,
        "commands": records,
        "network_isolation_claim": False,
        "evidence_boundary": (
            "A PASS means both default routes were positively observed absent, every "
            "enumerated non-loopback interface was classified inactive or as a known "
            "dormant macOS virtual interface with no non-link-local address, and each "
            "discovered Wi-Fi radio was positively observed Off. Command stdout is "
            "preserved for later review. Addresses retained on inactive macOS interfaces "
            "are recorded but are not alone treated as an active network path. This is "
            "not proof that every radio or covert channel is disabled."
        ),
    }


def _network_pass(report: Dict[str, Any], label: str) -> None:
    if report.get("schema") != NETWORK_SCHEMA or report.get("status") != "PASS":
        raise GateError(label + " network isolation check did not pass")


def _enumeration_view(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    # serial_client_registry_ids and serial_bsd_clients (schema 0.3+) are
    # deliberately excluded here: IORegistryEntryID values are assigned per
    # connection/boot, not a stable device property, so including them would
    # make a reconnect of the exact same physical device on the exact same
    # port compare unequal to its original review every time. The USB<->
    # serial ancestry check they support is a first-use admission concept
    # (see connection.inspect()/prepare()); a registered reconnect already
    # re-pins the same fingerprint and the same serial_port string, which
    # were already ancestry-verified once at registration time.
    usb_devices = snapshot.get("usb_devices")
    if isinstance(usb_devices, list):
        usb_devices = [
            {k: v for k, v in item.items() if k != "serial_client_registry_ids"}
            if isinstance(item, dict) else item
            for item in usb_devices
        ]
    return {
        "snapshot_complete": snapshot.get("snapshot_complete"),
        "usb_devices": usb_devices,
        "hid_devices": snapshot.get("hid_devices"),
        "disk_identifiers": snapshot.get("disk_identifiers"),
        "network_interfaces": snapshot.get("network_interfaces"),
        "system_extension_lines": snapshot.get("system_extension_lines"),
        "serial_paths": snapshot.get("serial_paths"),
    }


def derive_candidate(
    before: Dict[str, Any],
    after: Dict[str, Any],
    expected_vid: Optional[str],
    expected_pid: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    empty = admission.default_policy()
    initial = admission.evaluate(before, after, empty)
    delta = initial["delta"]
    new_usb = delta["new_usb_devices"]
    new_serial = delta["new_serial_paths"]
    cu_paths = [path for path in new_serial if path.startswith("/dev/cu.")]
    identity_check_only = expected_vid is None or expected_pid is None
    violations: List[str] = []
    if len(new_usb) != 1:
        violations.append(f"expected exactly one new USB identity, observed {len(new_usb)}")
    if identity_check_only and len(cu_paths) > 1:
        violations.append(f"expected at most one new /dev/cu.* path, observed {len(cu_paths)}")
    if not identity_check_only and len(cu_paths) != 1:
        violations.append(f"expected exactly one new /dev/cu.* path, observed {len(cu_paths)}")
    if new_usb:
        device = new_usb[0]
        if (
            expected_vid is not None
            and str(device.get("vendor_id", "")).lower() != expected_vid
        ):
            violations.append("new USB VID does not match the operator expectation")
        if (
            expected_pid is not None
            and str(device.get("product_id", "")).lower() != expected_pid
        ):
            violations.append("new USB PID does not match the operator expectation")
    for field, label in (
        ("new_hid_devices", "HID devices"),
        ("new_disk_identifiers", "disk identifiers"),
        ("new_network_interfaces", "network interfaces"),
        ("system_extension_changes", "system extension changes"),
        ("removed_usb_devices", "removed USB devices"),
        ("removed_hid_devices", "removed HID devices"),
        ("removed_disk_identifiers", "removed disk identifiers"),
        ("removed_network_interfaces", "removed network interfaces"),
        ("removed_serial_paths", "removed serial paths"),
    ):
        if delta[field]:
            violations.append(f"unexpected {label}: {len(delta[field])}")

    policy = admission.default_policy()
    policy["allowed_new_usb_fingerprints"] = [
        item["fingerprint_sha256"] for item in new_usb
    ]
    policy["allowed_new_serial_path_regexes"] = [re.escape(path) for path in new_serial]
    policy["note"] = (
        "First-use candidate policy generated from a reviewed stable-baseline to cable-only "
        "delta. This is not firmware authentication."
    )
    policy["self_sha256_without_this_field"] = _canonical_hash(policy)
    report = admission.evaluate(before, after, policy)
    if report["status"] != "PASS":
        violations.extend(report["violations"])
    summary = {
        "schema": SUMMARY_SCHEMA,
        "generated_utc": _utc_now(),
        "status": "REVIEW_REQUIRED" if not violations else "FAIL",
        "violations": sorted(set(violations)),
        "expected_vid": expected_vid,
        "expected_pid": expected_pid,
        "identity_check_only": identity_check_only,
        "new_usb_devices": new_usb,
        "new_serial_paths": new_serial,
        "before_snapshot_sha256": _canonical_hash(before),
        "after_snapshot_sha256": _canonical_hash(after),
        "candidate_policy_sha256": _canonical_hash(policy),
        "candidate_report_sha256": _canonical_hash(report),
        "manual_identity_review_required": True,
        "safe_to_forward_automatically": False,
        "badusb_prevention_claim": False,
    }
    summary["self_sha256_without_this_field"] = _canonical_hash(summary)
    return policy, report, summary


def _bind_candidate_topology(summary: Dict[str, Any]) -> None:
    """Seal the unverified-candidate flow to its actually observed USB path."""
    devices = summary.get("new_usb_devices")
    observed = False
    topology: List[str] = []
    if isinstance(devices, list) and len(devices) == 1 and isinstance(devices[0], dict):
        tree_path = devices[0].get("tree_path")
        if isinstance(tree_path, list) and tree_path and all(
            isinstance(item, str) and item for item in tree_path
        ):
            topology = list(tree_path)
            observed = topology[-1] == devices[0].get("_name")
    violations = summary.get("violations")
    if not isinstance(violations, list):
        violations = ["candidate violation list is malformed"]
    if not observed:
        violations.append("candidate topology is missing, malformed, or does not end at the candidate")
    summary["required_candidate_topology"] = "observed_baseline_relative_path"
    summary["candidate_topology_observed"] = observed
    summary["observed_candidate_topology"] = topology
    summary["candidate_topology_sha256"] = _canonical_hash(topology) if observed else None
    summary["violations"] = sorted(set(str(item) for item in violations))
    if summary["violations"]:
        summary["status"] = "FAIL"
    summary.pop("self_sha256_without_this_field", None)
    summary["self_sha256_without_this_field"] = _canonical_hash(summary)


def _bind_candidate_serial_ancestry(summary: Dict[str, Any], after_snapshot: Dict[str, Any]) -> None:
    """Verify the candidate /dev/cu.* path is an actual IORegistry descendant
    of the candidate USB device -- not merely inferred because there happens
    to be exactly one of each. See the USB<->serial ancestry audit handoff
    and f100_usb_admission.py's _ioreg_serial_client_registry_ids()/
    _normalize_serial_bsd_clients().

    This is additive to, not a replacement for, _bind_candidate_topology()
    above and every other existing check: it fails closed (adds a violation,
    forces status to FAIL) whenever the ancestry evidence is missing,
    incomplete, ambiguous, or points to a different device, and never
    upgrades a status on its own.
    """
    devices = summary.get("new_usb_devices")
    cu_paths = [
        path for path in summary.get("new_serial_paths", [])
        if isinstance(path, str) and path.startswith("/dev/cu.")
    ]
    violations = summary.get("violations")
    if not isinstance(violations, list):
        violations = ["candidate violation list is malformed"]
    verified = False
    if isinstance(devices, list) and len(devices) == 1 and isinstance(devices[0], dict) and len(cu_paths) == 1:
        device = devices[0]
        candidate_path = cu_paths[0]
        owned_ids = device.get("serial_client_registry_ids")
        clients = after_snapshot.get("serial_bsd_clients") if isinstance(after_snapshot, dict) else None
        if isinstance(owned_ids, list) and isinstance(clients, list):
            matching = [
                client for client in clients
                if isinstance(client, dict) and client.get("callout_device") == candidate_path
            ]
            if len(matching) == 1 and matching[0].get("registry_entry_id") in owned_ids:
                verified = True
    if not verified:
        violations.append(
            "candidate serial path is not a verified IORegistry descendant of the candidate USB device"
        )
    summary["candidate_serial_ancestry_verified"] = verified
    summary["violations"] = sorted(set(str(item) for item in violations))
    if summary["violations"]:
        summary["status"] = "FAIL"
    summary.pop("self_sha256_without_this_field", None)
    summary["self_sha256_without_this_field"] = _canonical_hash(summary)


def _validate_preauth_for_discovery(
    preauth_path: Path, session: Path
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validate one preauth summary against its discovery-session binding."""
    default_preauth = session / "preauth" / "preauth-summary.json"
    try:
        resolved_path = preauth_path.expanduser().resolve(strict=True)
        expected_path = default_preauth.resolve()
    except OSError as exc:
        raise GateError("preauth summary is unavailable: " + str(exc)) from exc
    if resolved_path != expected_path:
        raise GateError(
            "preauth summary must be the current session's "
            "mac-admission/preauth/preauth-summary.json"
        )
    try:
        preauth_payload = resolved_path.read_bytes()
    except OSError as exc:
        raise GateError("preauth summary is unavailable: " + str(exc)) from exc
    preauth = _decode_json_payload(preauth_payload, resolved_path)
    if preauth.get("schema") != PREAUTH_SUMMARY_SCHEMA:
        raise GateError("preauth summary has an unsupported schema")
    _validate_self_hash(preauth, "self_sha256_without_this_field", "preauth summary")
    if preauth.get("status") not in {"AUTH_REQUEST_OBSERVED", "NO_ENUMERATION"}:
        raise GateError("preauth summary is not eligible for post-authorization discovery")
    if preauth.get("eligible_only_for_cable_only_postauth_enumeration") is not True:
        raise GateError("preauth summary does not permit cable-only postauth enumeration")
    if preauth.get("safe_to_connect_f100") is not False:
        raise GateError("preauth summary camera boundary is malformed")
    integration_session_id = session.parent.name
    if not SESSION_ID_RE.fullmatch(integration_session_id):
        raise GateError("discovery parent is not a valid integration session ID")
    if preauth.get("integration_session_id") != integration_session_id:
        raise GateError("preauth summary belongs to a different integration session")
    expected_path_binding = _path_binding(session)
    if preauth.get("admission_session_path_sha256") != expected_path_binding:
        raise GateError("preauth summary belongs to a different admission path")
    binding_nonce = preauth.get("binding_nonce")
    if not isinstance(binding_nonce, str) or not BINDING_NONCE_RE.fullmatch(
        binding_nonce
    ):
        raise GateError("preauth summary binding nonce is malformed")
    preauth_binding = {
        "path": str(resolved_path),
        "file_sha256": hashlib.sha256(preauth_payload).hexdigest(),
        "status": preauth["status"],
        "integration_session_id": integration_session_id,
        "admission_session_path_sha256": expected_path_binding,
        "binding_nonce": binding_nonce,
    }
    return preauth, preauth_binding


def run_discovery(
    args: argparse.Namespace,
    *,
    snapshot_collector: Callable[[], Dict[str, Any]] = admission.collect_snapshot,
    network_collector: Callable[[], Dict[str, Any]] = collect_network_gate,
    prompt: Callable[[str], str] = input,
) -> Path:
    required = (
        args.ack_network_physically_isolated,
        args.ack_stable_usb_baseline,
        args.ack_camera_disconnected,
        args.ack_accessories_always_ask,
    )
    if not all(required):
        raise GateError("all four preparation acknowledgements are required")
    expected_vid_value = getattr(args, "expected_vid", None)
    expected_pid_value = getattr(args, "expected_pid", None)
    expected_vid = (
        _normalize_hex_id(expected_vid_value)
        if expected_vid_value is not None
        else None
    )
    expected_pid = (
        _normalize_hex_id(expected_pid_value)
        if expected_pid_value is not None
        else None
    )
    session = args.session.expanduser().resolve()
    if session.is_symlink():
        raise FileExistsError("refusing to use a symlink discovery session: " + str(session))
    if session.exists():
        existing_names = {item.name for item in session.iterdir()} if session.is_dir() else set()
        if not session.is_dir() or existing_names - {"preauth"}:
            raise FileExistsError(
                "discovery session must be new, empty, or contain only preauth evidence: "
                + str(session)
            )
    else:
        session.parent.resolve(strict=True)
        session.mkdir(mode=0o700)

    preauth_argument = getattr(args, "preauth_summary", None)
    preauth_path = preauth_argument.expanduser().resolve() if preauth_argument else None
    default_preauth = session / "preauth" / "preauth-summary.json"
    if preauth_path is None and default_preauth.exists():
        preauth_path = default_preauth
    if (session / "preauth").exists() and preauth_path is None:
        raise GateError("preauth directory exists but preauth-summary.json is missing")
    preauth_binding: Optional[Dict[str, Any]] = None
    if preauth_path is not None:
        _, preauth_binding = _validate_preauth_for_discovery(preauth_path, session)
    session_record = {
        "schema": SESSION_SCHEMA,
        "generated_utc": _utc_now(),
        "expected_vid": expected_vid,
        "expected_pid": expected_pid,
        "identity_check_only": expected_vid is None or expected_pid is None,
        "operator_assertions": {
            "network_physically_isolated": True,
            "existing_usb_state_stable_candidate_absent": True,
            "camera_powered_off_and_disconnected": True,
            "accessories_always_ask": True,
        },
        "required_candidate_topology": "observed_baseline_relative_path",
        "tool_opens_serial_or_controls_utm": False,
        "safe_to_forward_automatically": False,
        "preauth_summary_binding": preauth_binding,
    }
    session_record["self_sha256_without_this_field"] = _canonical_hash(session_record)
    _write_new(session / "session.json", session_record)

    network_before = network_collector()
    _write_new(session / "network-before.json", network_before)
    _network_pass(network_before, "before")
    before = snapshot_collector()
    before.pop("self_sha256_without_this_field", None)
    before["self_sha256_without_this_field"] = _canonical_hash(before)
    _write_new(session / "before.json", before)
    if before.get("snapshot_complete") is not True:
        raise GateError("USB baseline snapshot is incomplete")

    prompt(
        "Baseline captured. Connect ONLY the candidate cable/USB adapter using the "
        "intended direct port or already-present hub; keep the F100 disconnected. Handle the macOS accessory prompt, "
        "then press Enter to capture the delta. "
    )
    network_after = network_collector()
    _write_new(session / "network-after.json", network_after)
    _network_pass(network_after, "after")
    after = snapshot_collector()
    after.pop("self_sha256_without_this_field", None)
    after["self_sha256_without_this_field"] = _canonical_hash(after)
    _write_new(session / "after.json", after)
    if after.get("snapshot_complete") is not True:
        raise GateError("cable-only USB snapshot is incomplete")
    policy, report, summary = derive_candidate(
        before, after, expected_vid, expected_pid
    )
    _bind_candidate_topology(summary)
    _write_new(session / "candidate-policy.json", policy)
    _write_new(session / "candidate-report.json", report)
    _write_new(session / "discovery-summary.json", summary)
    return session / "discovery-summary.json"


def approve_candidate(args: argparse.Namespace) -> Path:
    session = args.session.expanduser().resolve(strict=True)
    if not args.ack_device_label_physically_reviewed:
        raise GateError("physical label/topology review acknowledgement is required")
    if not args.ack_logical_check_not_badusb_proof:
        raise GateError("logical-check limitation acknowledgement is required")
    fingerprint = args.fingerprint.lower()
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        raise GateError("fingerprint must be a full lowercase SHA-256")
    if not SERIAL_RE.fullmatch(args.serial_port):
        raise GateError("serial port must be an exact /dev/cu.* path")
    session_record = _load_json(session / "session.json")
    _validate_self_hash(
        session_record, "self_sha256_without_this_field", "discovery session"
    )
    if session_record.get("identity_check_only") is not False:
        raise GateError(
            "identity-check-only evidence cannot be promoted to manual approval"
        )
    if not isinstance(session_record.get("expected_vid"), str) or not isinstance(
        session_record.get("expected_pid"), str
    ):
        raise GateError("approval discovery session has no authoritative VID/PID")
    if session_record.get("required_candidate_topology") != "observed_baseline_relative_path":
        raise GateError("discovery session does not require an observed candidate topology")
    summary = _load_json(session / "discovery-summary.json")
    _validate_self_hash(
        summary, "self_sha256_without_this_field", "discovery summary"
    )
    if summary.get("schema") != SUMMARY_SCHEMA:
        raise GateError("discovery summary has an unsupported schema")
    if summary.get("required_candidate_topology") != "observed_baseline_relative_path" or summary.get(
        "candidate_topology_observed"
    ) is not True:
        raise GateError("discovery summary is not bound to the observed candidate topology")
    for field in ("identity_check_only", "expected_vid", "expected_pid"):
        if summary.get(field) != session_record.get(field):
            raise GateError(
                "discovery summary disagrees with the authoritative session: " + field
            )
    preauth_binding = _validate_bound_preauth(session_record)
    if summary.get("status") != "REVIEW_REQUIRED":
        raise GateError("discovery summary is not eligible for manual approval")
    devices = summary.get("new_usb_devices", [])
    if len(devices) != 1 or devices[0].get("fingerprint_sha256") != fingerprint:
        raise GateError("approved fingerprint does not exactly match the candidate")
    if args.serial_port not in summary.get("new_serial_paths", []):
        raise GateError("approved serial path is not in the candidate delta")
    before = _load_json(session / "before.json")
    after = _load_json(session / "after.json")
    policy = _load_json(session / "candidate-policy.json")
    _validate_sealed_discovery_input(
        before, admission.SNAPSHOT_SCHEMA, "before snapshot"
    )
    _validate_sealed_discovery_input(
        after, admission.SNAPSHOT_SCHEMA, "after snapshot"
    )
    _validate_sealed_discovery_input(
        policy, admission.POLICY_SCHEMA, "candidate policy"
    )
    for value, field, label in (
        (before, "before_snapshot_sha256", "before snapshot"),
        (after, "after_snapshot_sha256", "after snapshot"),
        (policy, "candidate_policy_sha256", "candidate policy"),
    ):
        if _canonical_hash(value) != summary.get(field):
            raise GateError(label + " disagrees with the sealed discovery summary")
    candidate_report = _load_json(session / "candidate-report.json")
    _validate_self_hash(
        candidate_report,
        "report_sha256_without_this_field",
        "candidate admission report",
    )
    if _canonical_hash(candidate_report) != summary.get("candidate_report_sha256"):
        raise GateError(
            "candidate admission report disagrees with the sealed discovery summary"
        )
    report = admission.evaluate(before, after, policy)
    if report.get("status") != "PASS":
        raise GateError("candidate no longer evaluates to PASS")
    _write_new(session / "policy.json", policy)
    _write_new(session / "report.json", report)
    approval = {
        "schema": APPROVAL_SCHEMA,
        "generated_utc": _utc_now(),
        "fingerprint_sha256": fingerprint,
        "serial_port": args.serial_port,
        "expected_vid": session_record["expected_vid"],
        "expected_pid": session_record["expected_pid"],
        "report_file_sha256": hashlib.sha256(
            (session / "report.json").read_bytes()
        ).hexdigest(),
        "operator_assertions": {
            "device_label_and_topology_physically_reviewed": True,
            "logical_check_is_not_badusb_or_electrical_proof": True,
            "f100_remains_disconnected": True,
        },
        "preauth_summary_binding": preauth_binding,
        "manual_utm_forwarding_only": True,
    }
    approval["self_sha256_without_this_field"] = _canonical_hash(approval)
    _write_new(session / "approval.json", approval)
    return session / "approval.json"


def _validate_self_hash(value: Dict[str, Any], field: str, label: str) -> None:
    declared = value.get(field)
    if not isinstance(declared, str):
        raise GateError(label + " self-hash is missing")
    copy = dict(value)
    del copy[field]
    if _canonical_hash(copy) != declared:
        raise GateError(label + " self-hash mismatch")


def _validate_sealed_discovery_input(
    value: Dict[str, Any], schema: str, label: str
) -> None:
    if value.get("schema") != schema:
        raise GateError(label + " has an unsupported schema")
    _validate_self_hash(value, "self_sha256_without_this_field", label)


def _validate_bound_preauth(session_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    binding = session_record.get("preauth_summary_binding")
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise GateError("preauth summary binding is malformed")
    path_value = binding.get("path")
    expected_hash = binding.get("file_sha256")
    expected_status = binding.get("status")
    expected_session_id = binding.get("integration_session_id")
    expected_path_binding = binding.get("admission_session_path_sha256")
    expected_nonce = binding.get("binding_nonce")
    if not all(
        isinstance(value, str)
        for value in (
            path_value,
            expected_hash,
            expected_status,
            expected_session_id,
            expected_path_binding,
            expected_nonce,
        )
    ):
        raise GateError("preauth summary binding fields are malformed")
    path = Path(path_value)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise GateError("bound preauth summary is unavailable: " + str(exc)) from exc
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise GateError("bound preauth summary file changed")
    preauth = _decode_json_payload(payload, path)
    if preauth.get("schema") != PREAUTH_SUMMARY_SCHEMA:
        raise GateError("bound preauth summary has an unsupported schema")
    _validate_self_hash(preauth, "self_sha256_without_this_field", "bound preauth summary")
    if preauth.get("status") != expected_status:
        raise GateError("bound preauth status changed")
    if expected_status not in {"AUTH_REQUEST_OBSERVED", "NO_ENUMERATION"}:
        raise GateError("bound preauth status is not eligible")
    if preauth.get("eligible_only_for_cable_only_postauth_enumeration") is not True:
        raise GateError("bound preauth eligibility changed")
    if preauth.get("safe_to_connect_f100") is not False:
        raise GateError("bound preauth camera boundary changed")
    if preauth.get("integration_session_id") != expected_session_id:
        raise GateError("bound preauth integration session changed")
    if preauth.get("admission_session_path_sha256") != expected_path_binding:
        raise GateError("bound preauth admission path changed")
    if preauth.get("binding_nonce") != expected_nonce:
        raise GateError("bound preauth nonce changed")
    if not SESSION_ID_RE.fullmatch(expected_session_id):
        raise GateError("bound preauth integration session is malformed")
    if not FINGERPRINT_RE.fullmatch(expected_path_binding):
        raise GateError("bound preauth admission path hash is malformed")
    if not BINDING_NONCE_RE.fullmatch(expected_nonce):
        raise GateError("bound preauth nonce is malformed")
    return dict(binding)


def reviewed_cable_network_exception(session: Path, identity: Dict[str, Any]) -> Dict[str, str]:
    """Validate an explicit, session/identity-bound operator exception; never claim isolation."""
    path = session / "reviewed-cable-network-exception.json"
    value = _load_json(path)
    _validate_self_hash(value, "self_sha256_without_this_field", "network exception")
    expected = {
        "schema": "f100-reviewed-cable-network-exception/0.1",
        "integration_session_id": session.parent.name,
        "admission_session_path_sha256": _path_binding(session),
        "scope": "network-isolation-only",
        "user_authorized": True,
        "expected_vid": identity.get("expected_vid"),
        "expected_pid": identity.get("expected_pid"),
        "fingerprint_sha256": identity.get("fingerprint_sha256"),
        "serial_port": identity.get("serial_port"),
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise GateError("network exception session/identity/scope mismatch")
    if not isinstance(value.get("authorization_source"), str) or not value["authorization_source"].strip():
        raise GateError("network exception has no authorization source")
    return {"path": str(path.resolve()), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def gate_for_manual_forwarding(
    args: argparse.Namespace,
    *,
    snapshot_collector: Callable[[], Dict[str, Any]] = admission.collect_snapshot,
    network_collector: Callable[[], Dict[str, Any]] = collect_network_gate,
    now: Optional[datetime] = None,
) -> Path:
    session = args.session.expanduser().resolve(strict=True)
    approval = _load_json(session / "approval.json")
    _validate_self_hash(approval, "self_sha256_without_this_field", "approval")
    approval_preauth = approval.get("preauth_summary_binding")
    session_record = _load_json(session / "session.json")
    _validate_self_hash(
        session_record, "self_sha256_without_this_field", "discovery session"
    )
    if session_record.get("identity_check_only") is not False:
        raise GateError(
            "identity-check-only evidence cannot reach the manual forwarding gate"
        )
    if not isinstance(session_record.get("expected_vid"), str) or not isinstance(
        session_record.get("expected_pid"), str
    ):
        raise GateError("forwarding discovery session has no authoritative VID/PID")
    summary = _load_json(session / "discovery-summary.json")
    _validate_self_hash(
        summary, "self_sha256_without_this_field", "discovery summary"
    )
    if summary.get("schema") != SUMMARY_SCHEMA:
        raise GateError("discovery summary has an unsupported schema")
    if session_record.get("required_candidate_topology") != "observed_baseline_relative_path":
        raise GateError("discovery session does not require an observed candidate topology")
    if summary.get("required_candidate_topology") != "observed_baseline_relative_path" or summary.get(
        "candidate_topology_observed"
    ) is not True:
        raise GateError("discovery summary is not bound to the observed candidate topology")
    for field in ("identity_check_only", "expected_vid", "expected_pid"):
        if summary.get(field) != session_record.get(field):
            raise GateError(
                "discovery summary disagrees with the authoritative session: " + field
            )
    for field in ("expected_vid", "expected_pid"):
        if approval.get(field) != session_record.get(field):
            raise GateError(
                "manual approval disagrees with the authoritative session: " + field
            )
    current_preauth = _validate_bound_preauth(session_record)
    if approval_preauth != current_preauth:
        raise GateError("approval preauth binding does not match the discovery session")
    report_path = session / "report.json"
    report = _load_json(report_path)
    _validate_self_hash(report, "report_sha256_without_this_field", "admission report")
    if report.get("status") != "PASS" or report.get("safe_to_forward_automatically") is not False:
        raise GateError("admission report is not a bounded PASS")
    if hashlib.sha256(report_path.read_bytes()).hexdigest() != approval.get("report_file_sha256"):
        raise GateError("approved admission report file changed")
    if args.serial_port != approval.get("serial_port"):
        raise GateError("gate serial port does not match the manual approval")
    generated = report.get("generated_utc")
    if not isinstance(generated, str):
        raise GateError("admission report timestamp is missing")
    try:
        created = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError("admission report timestamp is invalid") from exc
    current_time = now or datetime.now(timezone.utc)
    age = (current_time.astimezone(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    if age < -60 or age > args.max_age_seconds:
        raise GateError("admission report is stale for manual forwarding")

    network = network_collector()
    _write_new(session / "gate-network.json", network)
    exception_binding = None
    if getattr(args, "use_reviewed_cable_network_exception", False):
        exception_binding = reviewed_cable_network_exception(session, approval)
    else:
        _network_pass(network, "gate")
    current = snapshot_collector()
    _write_new(session / "gate-current.json", current)
    if current.get("snapshot_complete") is not True:
        raise GateError("gate-time USB snapshot is incomplete")
    after = _load_json(session / "after.json")
    _validate_sealed_discovery_input(
        after, admission.SNAPSHOT_SCHEMA, "after snapshot"
    )
    report_inputs = report.get("inputs")
    if not isinstance(report_inputs, dict) or report_inputs.get(
        "after_snapshot_sha256"
    ) != _canonical_hash(after):
        raise GateError("after snapshot disagrees with the approved admission report")
    if summary.get("after_snapshot_sha256") != _canonical_hash(after):
        raise GateError("after snapshot disagrees with the sealed discovery summary")
    if _canonical_hash(_enumeration_view(current)) != _canonical_hash(_enumeration_view(after)):
        raise GateError("USB/device enumeration changed after manual approval")

    result = {
        "schema": GATE_SCHEMA,
        "generated_utc": _utc_now(),
        "status": "PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW",
        "integration_session_id": session.parent.name,
        "admission_session_path_sha256": _path_binding(session),
        "serial_port": args.serial_port,
        "fingerprint_sha256": approval["fingerprint_sha256"],
        "admission_report_file": str(report_path.resolve()),
        "admission_report_file_sha256": hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest(),
        "manual_approval_file": str((session / "approval.json").resolve()),
        "manual_approval_file_sha256": hashlib.sha256(
            (session / "approval.json").read_bytes()
        ).hexdigest(),
        "admission_report_age_seconds": age,
        "current_enumeration_matches_reviewed_after": True,
        "network_gate_status": "EXEMPT_USER_REVIEWED_CABLE" if exception_binding else "PASS",
        "network_exception_binding": exception_binding,
        "utm_was_controlled": False,
        "serial_device_was_opened": False,
        "safe_to_forward_automatically": False,
        "hardware_validation": "NOT_ESTABLISHED",
        "badusb_prevention_claim": False,
        "evidence_boundary": (
            "This short-lived logical gate permits only a human decision about "
            "manual UTM USB forwarding. It does not authorize F100 connection, "
            "Connect/Download, serial I/O, or any camera command."
        ),
    }
    result["self_sha256_without_this_field"] = _canonical_hash(result)
    output = session / "utm-forwarding-gate.json"
    _write_new(output, result)
    return output


def _print_summary(path: Path) -> None:
    value = _load_json(path)
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    print("Summary=" + str(path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline Mac USB discovery and manual UTM-forwarding gate"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("checklist", help="print the offline operator checklist")

    run = sub.add_parser("run", help="interactive stable-baseline to cable-only discovery")
    run.add_argument("--session", type=Path, required=True)
    run.add_argument("--expected-vid", required=True)
    run.add_argument("--expected-pid", required=True)
    run.add_argument(
        "--preauth-summary",
        type=Path,
        help=(
            "compatibility spelling for SESSION/preauth/preauth-summary.json only; "
            "external paths are rejected and the in-session file is auto-detected"
        ),
    )
    run.add_argument("--ack-network-physically-isolated", action="store_true")
    run.add_argument("--ack-stable-usb-baseline", action="store_true")
    run.add_argument("--ack-camera-disconnected", action="store_true")
    run.add_argument("--ack-accessories-always-ask", action="store_true")

    approve = sub.add_parser("approve", help="bind a manually reviewed fingerprint/path")
    approve.add_argument("--session", type=Path, required=True)
    approve.add_argument("--fingerprint", required=True)
    approve.add_argument("--serial-port", required=True)
    approve.add_argument("--ack-device-label-physically-reviewed", action="store_true")
    approve.add_argument("--ack-logical-check-not-badusb-proof", action="store_true")

    gate = sub.add_parser("gate", help="short-lived recheck before manual UTM forwarding")
    gate.add_argument("--session", type=Path, required=True)
    gate.add_argument("--serial-port", required=True)
    gate.add_argument("--max-age-seconds", type=float, default=900)
    gate.add_argument("--use-reviewed-cable-network-exception", action="store_true")

    args = parser.parse_args()
    try:
        if args.action == "checklist":
            print(CHECKLIST)
            return 0
        if args.action == "run":
            path = run_discovery(args)
            _print_summary(path)
            return 4 if _load_json(path).get("status") == "REVIEW_REQUIRED" else 3
        if args.action == "approve":
            path = approve_candidate(args)
            print(path)
            print("ManualUTMForwardingOnly=true")
            return 0
        if args.max_age_seconds <= 0 or args.max_age_seconds > 900:
            raise GateError("--max-age-seconds must be greater than zero and no more than 900")
        path = gate_for_manual_forwarding(args)
        _print_summary(path)
        return 0
    except (GateError, OSError, ValueError, TypeError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 2
    except EOFError:
        print("error: input ended before the cable-connection confirmation", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
