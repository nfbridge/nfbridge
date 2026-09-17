#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only evidence collector for the USB<->serial-path ancestry audit.

Purpose
-------
The admission pipeline currently infers that a new USB device and a new
/dev/cu.* serial path are the same physical device purely by count (exactly
one of each). This script does not change that pipeline. It only observes,
from the real macOS IORegistry, whether the information needed to verify
that ancestry properly (rather than by count) is actually available, and
where. See the vendor-allowlist / USB<->serial-binding audit handoff for the
background.

What it does
------------
1. Runs the exact same command the existing admission snapshot collector
   already runs and is already trusted for USB identity:
       ioreg -a -r -c IOUSBHostDevice
   Unlike the existing normalizer (which only records IOUSBHostInterface
   descriptors and discards anything deeper), this script walks the FULL
   subtree under each matched USB device -- at any depth, including behind
   an internal hub -- and looks for any descendant whose IOKit class name
   contains "Serial" (case-insensitively; empirically this is
   IOSerialBSDClient, reached in practice through an intermediate
   IOUserSerial node such as "AppleUSBPLCOM" for Prolific on this macOS
   version). It records each one's IORegistryEntryID and the class-and-name
   ancestor chain from the USB device down to it.
2. ONE new command is introduced, of the same read-only registry-query shape
   as the existing one above:
       ioreg -a -r -c IOSerialBSDClient
   This is necessary, not optional: empirically, on this macOS version,
   `ioreg -a` omits IOCalloutDevice/IODialinDevice/IOTTYDevice/IOTTYBaseName
   from a node reached as a DESCENDANT of a different -c match (i.e. via
   step 1 above), but includes them when IOSerialBSDClient is itself the -c
   match target. This was verified directly against a live Prolific adapter
   on this Mac before being relied on (see the audit handoff). The two
   command outputs are joined purely by IORegistryEntryID, which both
   expose for the same physical registry node.
3. For anything found, it records the class-and-name ancestor chain from the
   USB device down to that node, its resolved /dev/cu.*//dev/tty.* path(s)
   from step 2, together with the USB device's already-collected identity
   fields (vendor/product id, name, serial number if present, manufacturer
   if present) -- the same fields the
   existing admission collector already records today. Nothing new is added
   to what this project already treats as USB identity evidence.
4. It cross-references the found IOCalloutDevice/IODialinDevice value(s)
   against the /dev/cu.*//dev/tty.* paths currently present (glob, the same
   mechanism the existing collector uses), so you can see plainly whether the
   node it found actually corresponds to a live serial port.
5. It writes ONE evidence JSON file scoped to the requested vendor id(s)
   only. It also includes the untouched raw ioreg subtree(s) for any USB
   device that matched a requested vendor id AND had a Serial-ish descendant,
   so the exact registry shape can be inspected precisely if the structured
   summary above misses something. It does NOT include unrelated USB
   devices, Wi-Fi, disks, network interfaces, system extensions, usernames,
   home paths, or any other system state.

What it never does
-------------------
- It never opens any serial port (no pyserial import, no device handle).
- It never sends any command to the F100 or any other device.
- It never writes anything except the one evidence file you point it at.

Usage
-----
    python3 collect_usb_serial_ancestry_evidence.py --vendor-id 0x0403 \
        --output ~/Desktop/nfbridge-ftdi-ancestry-evidence.json

    python3 collect_usb_serial_ancestry_evidence.py --vendor-id 0x067b \
        --output ~/Desktop/nfbridge-prolific-ancestry-evidence.json

Run each command with exactly one adapter connected (USB end only; the
camera side is not needed for this). See the audit handoff for the full
step-by-step procedure.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import f100_usb_admission as admission  # noqa: E402

# New command (see module docstring point 2): read-only, same shape as the
# existing COMMANDS["usb_ioreg"]. Empirically necessary because ioreg -a
# omits IOCalloutDevice/IODialinDevice/IOTTYDevice/IOTTYBaseName from a node
# reached as a descendant of a different -c match.
SERIAL_CLIENT_COMMAND = ["ioreg", "-a", "-r", "-c", "IOSerialBSDClient"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _collect_serial_bsd_clients_by_registry_id() -> Dict[int, Dict[str, Optional[str]]]:
    """Map IORegistryEntryID -> {IOCalloutDevice, IODialinDevice, IOTTYDevice,
    IOTTYBaseName} for every IOSerialBSDClient currently registered, queried
    directly (not as a descendant) so these properties are actually present.
    """
    result = admission._run_command(SERIAL_CLIENT_COMMAND)
    if not result.get("ok"):
        raise SystemExit("ioreg -c IOSerialBSDClient failed: " + repr(result))
    stdout = result["stdout"]
    if stdout == b"":
        return {}
    parsed = admission._load_unique_plist(stdout)
    nodes = parsed if isinstance(parsed, list) else [parsed]
    by_id: Dict[int, Dict[str, Optional[str]]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        registry_id = node.get("IORegistryEntryID")
        if not isinstance(registry_id, int) or isinstance(registry_id, bool):
            continue
        by_id[registry_id] = {
            key: node.get(key) if isinstance(node.get(key), str) else None
            for key in ("IOCalloutDevice", "IODialinDevice", "IOTTYDevice", "IOTTYBaseName")
        }
    return by_id


def _current_serial_paths() -> List[str]:
    found = set()
    for pattern in ("/dev/cu.*", "/dev/tty.*"):
        found.update(glob.glob(pattern))
    return sorted(found)


def _node_name(node: Dict[str, Any]) -> str:
    return admission._first_string(
        node, ("USB Product Name", "kUSBProductString", "IORegistryEntryName")
    ) or "<unnamed>"


def _find_serial_descendants(node: Dict[str, Any], chain: List[Dict[str, str]], *, is_start: bool = True):
    """Yield (ancestor_chain, callout_or_dialin_paths) for Serial-ish nodes
    within this USB device's own subtree.

    Stops descending at a NESTED IOUSBHostDevice boundary (except the
    starting node itself), so a serial descendant belonging to a child
    device attached downstream of this one is never wrongly attributed to
    this device -- mirroring the existing boundary-respecting pattern in
    f100_usb_admission.py's _ioreg_interface_descriptors().
    """
    node_class = admission._require_ioreg_node_class(node)
    if not is_start and node_class == admission._IOREG_USB_DEVICE_CLASS:
        return
    here = chain + [{"class": node_class, "name": _node_name(node)}]
    is_serial_class = "serial" in node_class.lower()
    registry_id = node.get("IORegistryEntryID")
    if is_serial_class and isinstance(registry_id, int) and not isinstance(registry_id, bool):
        yield here, registry_id
    for child in admission._ioreg_children(node):
        if isinstance(child, dict):
            yield from _find_serial_descendants(child, here, is_start=False)


def _find_usb_devices(node: Dict[str, Any]):
    """Yield every IOUSBHostDevice node anywhere in the tree, at any depth
    (e.g. behind an internal hub), not only top-level roots."""
    if not isinstance(node, dict):
        return
    node_class = admission._require_ioreg_node_class(node)
    if node_class == admission._IOREG_USB_DEVICE_CLASS:
        yield node
    for child in admission._ioreg_children(node):
        if isinstance(child, dict):
            yield from _find_usb_devices(child)


def _usb_device_identity(node: Dict[str, Any]) -> Dict[str, Any]:
    identity: Dict[str, Any] = {
        "_name": _node_name(node),
        "vendor_id": admission._format_usb_hex_id(node.get("idVendor"), "idVendor"),
        "product_id": admission._format_usb_hex_id(node.get("idProduct"), "idProduct"),
    }
    serial = admission._first_string(node, ("USB Serial Number", "kUSBSerialNumberString"))
    manufacturer = admission._first_string(node, ("USB Vendor Name", "kUSBVendorString"))
    if serial is not None:
        identity["serial_num"] = serial
    if manufacturer is not None:
        identity["manufacturer"] = manufacturer
    return identity


def _json_safe(value: Any) -> Any:
    """Plist parsing can yield bytes (binary <data> fields) and datetimes,
    neither of which json.dumps handles. Make the raw subtree serializable
    without dropping structure, for engineering inspection only."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex(), "__length__": len(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def collect(vendor_ids: List[str]) -> Dict[str, Any]:
    vendor_ids = [v.lower() for v in vendor_ids]
    result = admission._run_command(admission.COMMANDS["usb_ioreg"])
    if not result.get("ok"):
        raise SystemExit("ioreg command failed: " + repr(result))
    stdout = result["stdout"]
    # A successful recursive class query writes exactly zero bytes when no
    # IOUSBHostDevice exists -- the live representation of an empty device
    # set, not a malformed plist. See _normalize_ioreg_usb_command_output().
    if stdout == b"":
        roots: List[Any] = []
    else:
        parsed = admission._load_unique_plist(stdout)
        roots = parsed if isinstance(parsed, list) else [parsed]

    serial_clients_by_id = _collect_serial_bsd_clients_by_registry_id()

    matches: List[Dict[str, Any]] = []
    for top in roots:
        for device in _find_usb_devices(top):
            try:
                identity = _usb_device_identity(device)
            except ValueError:
                continue
            if identity["vendor_id"] not in vendor_ids:
                continue
            serial_hits = list(_find_serial_descendants(device, []))
            descendants = []
            for chain, registry_id in serial_hits:
                paths = serial_clients_by_id.get(registry_id)
                descendants.append({
                    "ancestor_chain": chain,
                    "registry_entry_id": registry_id,
                    "resolved_paths": paths,  # None if this registry_id wasn't found in the direct IOSerialBSDClient query
                })
            matches.append({
                "usb_device": identity,
                "serial_descendants_found": len(serial_hits) > 0,
                "serial_descendants": descendants,
                "raw_subtree": _json_safe(device) if serial_hits else None,
            })

    live_serial_paths = _current_serial_paths()
    return {
        "schema": "nfbridge-usb-serial-ancestry-evidence/0.2",
        "generated_utc": _utc_now(),
        "requested_vendor_ids": vendor_ids,
        "live_dev_cu_and_tty_paths": live_serial_paths,
        "matched_usb_devices": matches,
        "evidence_boundary": (
            "Scoped to the requested vendor id(s) only. Contains USB identity "
            "fields already collected by the existing admission snapshot "
            "(name, vendor/product id, serial number and manufacturer if "
            "present) plus, only for a matched device, its raw IORegistry "
            "subtree and its IOSerialBSDClient descendant(s)' resolved "
            "/dev/cu.*//dev/tty.* paths. Does not include Wi-Fi, disks, "
            "network interfaces, system extensions, usernames, or home "
            "paths. Never opens a serial port and never sends a command to "
            "any device."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vendor-id", action="append", required=True,
                         help="USB vendor id to scope evidence to, e.g. 0x0403 or 0x067b. Repeatable.")
    parser.add_argument("--output", required=True, help="Path to write the evidence JSON file.")
    args = parser.parse_args()

    evidence = collect(args.vendor_id)
    output_path = Path(args.output).expanduser()
    if output_path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output_path}")
    output_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    found = [m for m in evidence["matched_usb_devices"] if m["serial_descendants_found"]]
    print(f"Wrote {output_path}")
    print(f"USB devices matching requested vendor id(s): {len(evidence['matched_usb_devices'])}")
    print(f"...with a Serial-ish descendant found: {len(found)}")
    if not evidence["matched_usb_devices"]:
        print("No USB device with the requested vendor id is currently connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
