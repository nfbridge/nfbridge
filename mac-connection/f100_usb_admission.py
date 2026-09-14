#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only macOS USB admission snapshots and fail-closed delta evaluation.

The tool detects unexpected logical device classes and topology changes.  It
does not prevent a permitted BadUSB HID from acting, authenticate firmware, or
establish electrical safety.  Keep macOS "Allow accessories to connect" set to
Always Ask and do not pass a device to UTM until a reviewed report passes.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import plistlib
import platform
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree
from xml.parsers import expat


SNAPSHOT_SCHEMA = "f100-usb-admission-snapshot/0.2"
POLICY_SCHEMA = "f100-usb-admission-policy/0.1"
REPORT_SCHEMA = "f100-usb-admission-report/0.1"

COMMANDS = {
    # IORegistry is the primary USB identity source.  On the target macOS
    # 26 host, system_profiler can return a syntactically valid but empty
    # SPUSBDataType array while the FTDI serial node and other USB devices are
    # already present.  Keep system_profiler as a required independent
    # diagnostic/cross-check, but never let its empty array erase IORegistry
    # identities.
    "usb_ioreg": ["ioreg", "-a", "-r", "-c", "IOUSBHostDevice"],
    "usb_system_profiler": ["system_profiler", "SPUSBDataType", "-json"],
    "hid": ["ioreg", "-a", "-r", "-c", "IOHIDDevice"],
    "disks": ["diskutil", "list", "-plist"],
    "interfaces": ["ifconfig", "-l"],
    "system_extensions": ["systemextensionsctl", "list"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _UniqueKeyDict(dict):
    """Reject invalid plist dictionary keys before normalization can erase them."""

    def __setitem__(self, key: Any, value: Any) -> None:
        if type(key) is not str:
            raise ValueError("plist contains a non-string dictionary key")
        if key in self:
            raise ValueError("plist contains a duplicate dictionary key")
        super().__setitem__(key, value)


_PLIST_SCALAR_TAGS = {"data", "date", "false", "integer", "real", "string", "true"}
_XML_WHITESPACE = frozenset(" \t\r\n")


def _has_non_xml_whitespace(text: Optional[str]) -> bool:
    """Return whether XML character data contains anything outside XML 1.0 S."""

    return text is not None and any(char not in _XML_WHITESPACE for char in text)


def _validate_xml_plist_structure(payload: bytes) -> None:
    """Reject XML constructs that plistlib otherwise accepts by discarding data."""

    declared_versions: List[str] = []
    declaration_parser = expat.ParserCreate()
    declaration_parser.XmlDeclHandler = (
        lambda version, _encoding, _standalone: declared_versions.append(version)
    )
    try:
        declaration_parser.Parse(payload, True)
    except expat.ExpatError as exc:
        raise ValueError("plist XML is malformed: " + str(exc)) from exc
    if declared_versions and declared_versions != ["1.0"]:
        raise ValueError("plist XML declaration has an unsupported version")

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("plist XML is malformed: " + str(exc)) from exc

    if root.tag != "plist" or root.attrib != {"version": "1.0"}:
        raise ValueError("plist XML has an invalid root envelope")
    if _has_non_xml_whitespace(root.text):
        raise ValueError("plist XML contains text outside its root value")
    if len(root) != 1:
        raise ValueError("plist XML must contain exactly one root value")

    def validate_value(node: ElementTree.Element) -> None:
        if node.attrib:
            raise ValueError("plist XML value contains unsupported attributes")

        if node.tag == "dict":
            if _has_non_xml_whitespace(node.text):
                raise ValueError("plist XML dictionary contains stray text")
            children = list(node)
            if len(children) % 2:
                raise ValueError("plist XML dictionary has an unmatched key")
            for index in range(0, len(children), 2):
                key = children[index]
                if key.tag != "key" or key.attrib or len(key):
                    raise ValueError("plist XML dictionary key is invalid")
                if _has_non_xml_whitespace(key.tail):
                    raise ValueError("plist XML dictionary contains stray text")
                value = children[index + 1]
                validate_value(value)
                if _has_non_xml_whitespace(value.tail):
                    raise ValueError("plist XML dictionary contains stray text")
            return

        if node.tag == "array":
            if _has_non_xml_whitespace(node.text):
                raise ValueError("plist XML array contains stray text")
            for value in node:
                validate_value(value)
                if _has_non_xml_whitespace(value.tail):
                    raise ValueError("plist XML array contains stray text")
            return

        if node.tag not in _PLIST_SCALAR_TAGS or len(node):
            raise ValueError("plist XML contains an unsupported value element")
        if node.tag in {"true", "false"} and _has_non_xml_whitespace(node.text):
            raise ValueError("plist XML boolean contains unexpected text")

    root_value = root[0]
    validate_value(root_value)
    if _has_non_xml_whitespace(root_value.tail):
        raise ValueError("plist XML contains text after its root value")


def _load_unique_plist(payload: bytes) -> Any:
    # plistlib otherwise keeps only the last value for a duplicate XML or
    # binary dictionary key. A rejecting dict_type preserves that raw-input
    # distinction for both parser implementations.
    if not payload.startswith(b"bplist00"):
        _validate_xml_plist_structure(payload)
    return plistlib.loads(payload, dict_type=_UniqueKeyDict)


def _unique_json_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _load_unique_json(payload: str) -> Any:
    return json.loads(payload, object_pairs_hook=_unique_json_object)


def _write_new_json(path: Path, value: Any) -> None:
    requested = path.expanduser()
    if requested.name in ("", ".", ".."):
        raise ValueError("output must name a new file")
    parent = requested.parent.resolve(strict=True)
    destination = parent / requested.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("refusing to overwrite existing evidence: " + str(destination))
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def _run_command(command: Sequence[str], timeout: float = 30.0) -> Dict[str, Any]:
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
        return {
            "ok": False,
            "exit_code": None,
            "stdout": b"",
            "stderr": str(exc),
        }
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr.decode("utf-8", "replace"),
    }


def _pick(mapping: Dict[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    selected: Dict[str, Any] = {}
    for name in names:
        if name in mapping:
            value = mapping[name]
            if isinstance(value, bytes):
                value = value.hex()
            selected[name] = value
    return selected


_VOLATILE_USB_KEYS = {
    "location_id",
    "current_available",
    "current_required",
    "extra_current_operating",
    "sleep_current",
}


def _stable_usb_subtree(value: Any) -> Any:
    """Retain descriptor/class topology while dropping host-location/power noise."""
    if isinstance(value, dict):
        return {
            key: _stable_usb_subtree(child)
            for key, child in sorted(value.items())
            if key not in _VOLATILE_USB_KEYS
        }
    if isinstance(value, list):
        return [_stable_usb_subtree(child) for child in value]
    return value


def _normalize_usb(payload: bytes) -> List[Dict[str, Any]]:
    """Normalize the legacy system_profiler USB JSON for cross-checking."""
    parsed = _load_unique_json(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("system_profiler USB JSON root is not an object")
    roots = parsed.get("SPUSBDataType")
    if not isinstance(roots, list):
        raise ValueError("SPUSBDataType is not a list")
    devices: List[Dict[str, Any]] = []
    identity_fields = (
        "_name",
        "vendor_id",
        "product_id",
        "serial_num",
        "manufacturer",
        "bcd_device",
        "device_speed",
        "location_id",
        "usb_device_class",
        "usb_device_class_id",
        "usb_device_subclass",
        "usb_device_protocol",
        "driver_name",
    )

    def walk(items: List[Any], ancestors: Tuple[str, ...]) -> None:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("SPUSBDataType contains a non-dictionary entry")
            string_fields = (
                "_name",
                "serial_num",
                "manufacturer",
                "usb_device_class",
                "driver_name",
            )
            scalar_fields = (
                "vendor_id",
                "product_id",
                "bcd_device",
                "device_speed",
                "location_id",
                "usb_device_class_id",
                "usb_device_subclass",
                "usb_device_protocol",
            )
            for field in string_fields:
                if field in item and (
                    type(item[field]) is not str or not item[field]
                ):
                    raise ValueError(
                        "system_profiler " + field + " is not a non-empty string"
                    )
            for field in scalar_fields:
                if field in item and not (
                    type(item[field]) is int
                    or (type(item[field]) is str and bool(item[field]))
                ):
                    raise ValueError(
                        "system_profiler " + field + " has an invalid scalar type"
                    )
            name = item.get("_name", "<unnamed>")
            path = ancestors + (name,)
            selected = _pick(item, identity_fields)
            if any(key in selected for key in ("vendor_id", "product_id", "serial_num")):
                # The whole descriptor subtree is deliberate: a composite device
                # that adds an HID/storage/network child must not retain the same
                # fingerprint merely because its top-level VID/PID are unchanged.
                stable = _stable_usb_subtree(item)
                selected["tree_path"] = list(path)
                selected["fingerprint_sha256"] = _canonical_hash(stable)
                devices.append(selected)
            if "_items" in item:
                children = item["_items"]
                if not isinstance(children, list):
                    raise ValueError("system_profiler _items is not a list")
                walk(children, path)

    walk(roots, ())
    return sorted(
        devices,
        key=lambda item: (item.get("fingerprint_sha256", ""), item.get("location_id", "")),
    )


_IOREG_CHILDREN = "IORegistryEntryChildren"
_IOREG_USB_DEVICE_CLASS = "IOUSBHostDevice"
_IOREG_INTERFACE_FIELDS = (
    "IOObjectClass",
    "IORegistryEntryName",
    "bInterfaceNumber",
    "bAlternateSetting",
    "bInterfaceClass",
    "bInterfaceSubClass",
    "bInterfaceProtocol",
    "bNumEndpoints",
    "bConfigurationValue",
)

_IOREG_DEVICE_STRING_FIELDS = (
    "USB Product Name",
    "kUSBProductString",
    "IORegistryEntryName",
    "USB Serial Number",
    "kUSBSerialNumberString",
    "USB Vendor Name",
    "kUSBVendorString",
    "UsbExclusiveOwner",
)

_IOREG_DEVICE_NUMERIC_FIELDS = {
    "bDeviceClass": 0xFF,
    "bDeviceSubClass": 0xFF,
    "bDeviceProtocol": 0xFF,
    "bcdDevice": 0xFFFF,
    "Device Speed": 0xFF,
}

_IOREG_INTERFACE_NUMERIC_FIELDS = {
    "bInterfaceNumber": 0xFF,
    "bAlternateSetting": 0xFF,
    "bInterfaceClass": 0xFF,
    "bInterfaceSubClass": 0xFF,
    "bInterfaceProtocol": 0xFF,
    "bNumEndpoints": 0xFF,
    "bConfigurationValue": 0xFF,
}


def _first_string(mapping: Dict[str, Any], names: Iterable[str]) -> Optional[str]:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _require_ioreg_node_class(node: Dict[str, Any]) -> str:
    value = node.get("IOObjectClass")
    if not isinstance(value, str) or not value:
        raise ValueError("IORegistry node IOObjectClass is missing or is not a non-empty string")
    return value


def _validate_optional_nonempty_strings(
    mapping: Dict[str, Any], names: Iterable[str]
) -> None:
    for name in names:
        if name not in mapping:
            continue
        value = mapping[name]
        if not isinstance(value, str) or not value:
            raise ValueError(name + " is not a non-empty string")


def _validate_optional_unsigned_integers(
    mapping: Dict[str, Any], fields: Dict[str, int]
) -> None:
    for name, maximum in fields.items():
        if name not in mapping:
            continue
        value = mapping[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= maximum
        ):
            raise ValueError(
                f"{name} is not an unsigned integer in the range 0..{maximum}"
            )


def _ioreg_children(node: Dict[str, Any]) -> List[Any]:
    if _IOREG_CHILDREN not in node:
        return []
    children = node[_IOREG_CHILDREN]
    if not isinstance(children, list):
        raise ValueError("IORegistryEntryChildren is not a list")
    return children


def _format_usb_hex_id(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise ValueError(label + " must be a USB numeric identifier")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        # system_profiler commonly appends a human vendor label, e.g.
        # ``0x0403  (Future Technology Devices International Limited)``.
        matched = re.fullmatch(
            r"\s*(?:0x)?([0-9A-Fa-f]{1,4})(?:\s+\([^()\r\n]*\))?\s*",
            value,
        )
        if not matched:
            raise ValueError(label + " has an invalid USB identifier")
        number = int(matched.group(1), 16)
    else:
        raise ValueError(label + " is missing or has an invalid type")
    if not 0 <= number <= 0xFFFF:
        raise ValueError(label + " is outside the USB identifier range")
    return f"0x{number:04x}"


def _ioreg_usb_device_name(item: Dict[str, Any]) -> str:
    return _first_string(
        item,
        (
            "USB Product Name",
            "kUSBProductString",
            "IORegistryEntryName",
        ),
    ) or "<unnamed USB device>"


def _ioreg_interface_descriptors(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Capture stable USB interface descriptors, not volatile driver state.

    The IORegistry subtree also contains live clients, power counters, disk
    stacks, and timings.  Hashing those would make an unchanged USB device
    appear different between two snapshots.  USB interface descriptors are
    retained so a composite device that adds HID/storage/network interfaces
    cannot keep the same fingerprint.
    """

    descriptors: List[Dict[str, Any]] = []

    def walk(node: Dict[str, Any]) -> None:
        node_class = _require_ioreg_node_class(node)
        if node is not item and node_class == _IOREG_USB_DEVICE_CLASS:
            return
        if node_class == "IOUSBHostInterface":
            _validate_optional_nonempty_strings(node, ("IORegistryEntryName",))
            _validate_optional_unsigned_integers(
                node, _IOREG_INTERFACE_NUMERIC_FIELDS
            )
            descriptors.append(_pick(node, _IOREG_INTERFACE_FIELDS))
        for child in _ioreg_children(node):
            if not isinstance(child, dict):
                raise ValueError("IORegistryEntryChildren contains a non-dictionary entry")
            walk(child)

    walk(item)
    return sorted(descriptors, key=_canonical_hash)


def _normalize_ioreg_usb(payload: bytes) -> List[Dict[str, Any]]:
    """Normalize IOUSBHostDevice plist output and preserve hub ancestry."""

    parsed = _load_unique_plist(payload)
    if isinstance(parsed, dict):
        roots = [parsed]
    elif isinstance(parsed, list):
        roots = parsed
    else:
        raise ValueError("IOUSBHostDevice plist is not a list or dictionary")

    # The recursive class query returns a hub's nested devices and also returns
    # each matching nested device as another top-level root.  Registry entry ID
    # is therefore used only to deduplicate the same observation.  It is not
    # part of the stable device fingerprint.
    observations: Dict[int, Dict[str, Any]] = {}

    def walk(node: Dict[str, Any], usb_ancestors: Tuple[str, ...]) -> None:
        node_class = _require_ioreg_node_class(node)
        current_ancestors = usb_ancestors
        if node_class == _IOREG_USB_DEVICE_CLASS:
            _validate_optional_nonempty_strings(node, _IOREG_DEVICE_STRING_FIELDS)
            _validate_optional_unsigned_integers(node, _IOREG_DEVICE_NUMERIC_FIELDS)
            registry_id = node.get("IORegistryEntryID")
            if isinstance(registry_id, bool) or not isinstance(registry_id, int) or registry_id <= 0:
                raise ValueError("IOUSBHostDevice has no valid IORegistryEntryID")
            name = _ioreg_usb_device_name(node)
            path = usb_ancestors + (name,)
            vendor_id = _format_usb_hex_id(node.get("idVendor"), "idVendor")
            product_id = _format_usb_hex_id(node.get("idProduct"), "idProduct")
            selected: Dict[str, Any] = {
                "_name": name,
                "vendor_id": vendor_id,
                "product_id": product_id,
            }
            serial = _first_string(
                node, ("USB Serial Number", "kUSBSerialNumberString")
            )
            manufacturer = _first_string(
                node, ("USB Vendor Name", "kUSBVendorString")
            )
            if serial is not None:
                selected["serial_num"] = serial
            if manufacturer is not None:
                selected["manufacturer"] = manufacturer
            for output_name, input_name in (
                ("bcd_device", "bcdDevice"),
                ("device_speed", "Device Speed"),
                ("usb_device_class_id", "bDeviceClass"),
                ("usb_device_subclass", "bDeviceSubClass"),
                ("usb_device_protocol", "bDeviceProtocol"),
                ("driver_name", "UsbExclusiveOwner"),
            ):
                if input_name in node:
                    selected[output_name] = node[input_name]
            if "locationID" in node:
                location = node["locationID"]
                if isinstance(location, bool) or not isinstance(location, int):
                    raise ValueError("IOUSBHostDevice locationID has an invalid type")
                selected["location_id"] = f"0x{location:08x}"

            interfaces = _ioreg_interface_descriptors(node)
            selected["interfaces"] = interfaces
            stable = {
                key: value
                for key, value in selected.items()
                if key not in {"location_id", "tree_path", "fingerprint_sha256"}
            }
            selected["tree_path"] = list(path)
            selected["fingerprint_sha256"] = _canonical_hash(stable)

            previous = observations.get(registry_id)
            if previous is not None:
                if previous["fingerprint_sha256"] != selected["fingerprint_sha256"]:
                    raise ValueError("duplicate IORegistryEntryID has conflicting descriptors")
                if previous.get("location_id") != selected.get("location_id"):
                    raise ValueError("duplicate IORegistryEntryID has conflicting locations")
                old_path = previous.get("tree_path", [])
                if len(path) > len(old_path):
                    observations[registry_id] = selected
                elif len(path) == len(old_path) and list(path) != old_path:
                    raise ValueError("duplicate IORegistryEntryID has ambiguous topology")
            else:
                observations[registry_id] = selected
            current_ancestors = path

        for child in _ioreg_children(node):
            if not isinstance(child, dict):
                raise ValueError("IORegistryEntryChildren contains a non-dictionary entry")
            walk(child, current_ancestors)

    for root in roots:
        if not isinstance(root, dict):
            raise ValueError("IOUSBHostDevice plist contains a non-dictionary root")
        walk(root, ())

    return sorted(
        observations.values(),
        key=lambda item: (item["fingerprint_sha256"], item.get("location_id", "")),
    )


def _normalize_ioreg_usb_command_output(payload: bytes) -> List[Dict[str, Any]]:
    """Normalize the actual output contract of the recursive ioreg query.

    On the target macOS host, a successful recursive class query writes exactly
    zero bytes when no IOUSBHostDevice exists.  That is the live representation
    of an empty device set, not a malformed plist.  Keep every non-empty payload
    on the strict plist path so whitespace or other malformed output still
    fails closed.
    """

    if payload == b"":
        return []
    return _normalize_ioreg_usb(payload)


def _crosscheck_system_profiler_usb(
    ioreg_devices: Sequence[Dict[str, Any]],
    profiler_devices: Sequence[Dict[str, Any]],
) -> None:
    """Require every profiler identity to have an IORegistry counterpart.

    system_profiler may omit every device on the target host, so an empty list
    is diagnostic rather than authoritative.  A non-empty contradictory list
    is rejected.  IORegistry may legitimately contain more devices than the
    higher-level report and is therefore the primary superset.
    """

    remaining = list(ioreg_devices)
    # Match the most constrained observations first. Otherwise an earlier
    # serial-less profiler entry could consume the only IORegistry device
    # needed by a later exact-serial entry with the same VID/PID.
    ordered_profiler = sorted(
        profiler_devices,
        key=lambda item: item.get("serial_num") is None,
    )
    for profiler in ordered_profiler:
        vendor_id = _format_usb_hex_id(profiler.get("vendor_id"), "vendor_id")
        product_id = _format_usb_hex_id(profiler.get("product_id"), "product_id")
        serial = profiler.get("serial_num")
        if serial is not None and not isinstance(serial, str):
            raise ValueError("system_profiler serial_num has an invalid type")
        matched_index = None
        for index, observed in enumerate(remaining):
            if observed.get("vendor_id") != vendor_id or observed.get("product_id") != product_id:
                continue
            if serial is not None and observed.get("serial_num") != serial:
                continue
            matched_index = index
            break
        if matched_index is None:
            raise ValueError(
                "system_profiler USB identity is absent from the IORegistry primary source"
            )
        remaining.pop(matched_index)


def _normalize_hid(payload: bytes) -> List[Dict[str, Any]]:
    parsed = _load_unique_plist(payload)
    if isinstance(parsed, dict):
        items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError("IOHIDDevice plist is not a list or dictionary")
    fields = (
        "Product",
        "Manufacturer",
        "VendorID",
        "ProductID",
        "Transport",
        "SerialNumber",
        "PrimaryUsagePage",
        "PrimaryUsage",
        "LocationID",
        "Built-In",
    )
    string_fields = {
        "Product",
        "Manufacturer",
        "Transport",
        "SerialNumber",
    }
    integer_fields = {
        "VendorID",
        "ProductID",
        "PrimaryUsagePage",
        "PrimaryUsage",
        "LocationID",
    }
    result: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("IOHIDDevice plist contains a non-dictionary entry")
        # Validate the plist source objects before selecting them.  The generic
        # _pick helper hex-encodes bytes for JSON compatibility; using it first
        # would turn a malformed bytes-valued HID name into a plausible string
        # and could collide with a genuine hex-looking identity value.
        selected = {name: item[name] for name in fields if name in item}
        if not selected:
            raise ValueError("IOHIDDevice entry has no recognized identity fields")
        for name in string_fields:
            if name not in selected:
                continue
            if type(selected[name]) is not str:
                raise ValueError(name + " is not a string")
            # Current Apple-silicon Macs can expose built-in SPU HID entries
            # with an explicitly empty serial descriptor. Preserve that exact
            # value in the fingerprint. Keep the former non-empty requirement
            # for every other string field and for external HID serials.
            if not selected[name] and not (
                name == "SerialNumber" and selected.get("Built-In") is True
            ):
                raise ValueError(name + " is not a non-empty string")
        for name in integer_fields:
            if name in selected and (
                type(selected[name]) is not int or selected[name] < 0
            ):
                raise ValueError(name + " is not an unsigned integer")
        if "Built-In" in selected and type(selected["Built-In"]) is not bool:
            raise ValueError("Built-In is not a boolean")
        stable = dict(selected)
        stable.pop("LocationID", None)
        selected["fingerprint_sha256"] = _canonical_hash(stable)
        result.append(selected)
    return sorted(result, key=lambda item: item["fingerprint_sha256"])


def _normalize_disks(payload: bytes) -> List[str]:
    parsed = _load_unique_plist(payload)
    if not isinstance(parsed, dict):
        raise ValueError("diskutil plist root is not a dictionary")
    all_disks = parsed.get("AllDisks")
    if not isinstance(all_disks, list):
        raise ValueError("diskutil AllDisks is not a list")
    if not all(type(identifier) is str and identifier for identifier in all_disks):
        raise ValueError("diskutil AllDisks contains an invalid identifier")
    if len(all_disks) != len(set(all_disks)):
        raise ValueError("diskutil AllDisks contains duplicate identifiers")

    all_disk_set = set(all_disks)

    # These top-level containers are set-like string lists in diskutil's plist
    # shape. Validate uniqueness for both. WholeDisks contains disk identifiers
    # and must agree with AllDisks; VolumesFromDisks has distinct field semantics
    # and is deliberately not treated as an AllDisks subset.
    for name in ("WholeDisks", "VolumesFromDisks"):
        if name not in parsed:
            continue
        values = parsed[name]
        if not isinstance(values, list) or not all(
            type(identifier) is str and identifier for identifier in values
        ):
            raise ValueError("diskutil " + name + " is not a list of identifiers")
        if len(values) != len(set(values)):
            raise ValueError("diskutil " + name + " contains duplicate identifiers")
        if name == "WholeDisks" and not set(values).issubset(all_disk_set):
            raise ValueError("diskutil " + name + " contradicts AllDisks")

    if "AllDisksAndPartitions" in parsed:
        hierarchy = parsed["AllDisksAndPartitions"]
        if not isinstance(hierarchy, list) or not all(
            isinstance(item, dict) for item in hierarchy
        ):
            raise ValueError(
                "diskutil AllDisksAndPartitions is not a list of dictionaries"
            )

        hierarchy_identifiers: List[str] = []
        physical_store_identifiers: List[str] = []

        def validate_hierarchy_node(node: Dict[str, Any]) -> None:
            identifier = node.get("DeviceIdentifier")
            if type(identifier) is not str or not identifier:
                raise ValueError(
                    "diskutil hierarchy entry has no valid DeviceIdentifier"
                )
            hierarchy_identifiers.append(identifier)
            # diskutil represents ordinary partition children in Partitions
            # and APFS logical-volume children in APFSVolumes. APFSPhysicalStores
            # are references back to existing partition nodes, not additional
            # hierarchy nodes. Validate their own container and identifiers
            # without double-counting them as hierarchy children.
            if "APFSPhysicalStores" in node:
                stores = node["APFSPhysicalStores"]
                if not isinstance(stores, list) or not all(
                    isinstance(store, dict) for store in stores
                ):
                    raise ValueError(
                        "diskutil hierarchy APFSPhysicalStores is not a list "
                        "of dictionaries"
                    )
                for store in stores:
                    store_identifier = store.get("DeviceIdentifier")
                    if type(store_identifier) is not str or not store_identifier:
                        raise ValueError(
                            "diskutil APFSPhysicalStores entry has no valid "
                            "DeviceIdentifier"
                        )
                    if store_identifier == identifier:
                        raise ValueError(
                            "diskutil APFSPhysicalStores contains a self-reference"
                        )
                    forbidden_children = {
                        "Partitions",
                        "APFSVolumes",
                        "APFSPhysicalStores",
                    }.intersection(store)
                    if forbidden_children:
                        raise ValueError(
                            "diskutil APFSPhysicalStores entry contains a hierarchy field"
                        )
                    physical_store_identifiers.append(store_identifier)
            for child_name in ("Partitions", "APFSVolumes"):
                if child_name not in node:
                    continue
                children = node[child_name]
                if not isinstance(children, list) or not all(
                    isinstance(child, dict) for child in children
                ):
                    raise ValueError(
                        "diskutil hierarchy "
                        + child_name
                        + " is not a list of dictionaries"
                    )
                for child in children:
                    validate_hierarchy_node(child)

        for item in hierarchy:
            validate_hierarchy_node(item)
        if len(hierarchy_identifiers) != len(set(hierarchy_identifiers)):
            raise ValueError("diskutil hierarchy contains duplicate identifiers")
        if len(physical_store_identifiers) != len(
            set(physical_store_identifiers)
        ):
            raise ValueError(
                "diskutil APFSPhysicalStores contains duplicate identifiers"
            )
        if set(hierarchy_identifiers) != all_disk_set:
            raise ValueError("diskutil hierarchy contradicts AllDisks")

    supplied_device_identifiers: List[str] = []

    def validate_identifiers(value: Any) -> None:
        if isinstance(value, dict):
            if "DeviceIdentifier" in value and (
                type(value["DeviceIdentifier"]) is not str
                or not value["DeviceIdentifier"]
            ):
                raise ValueError("diskutil DeviceIdentifier is invalid")
            if "DeviceIdentifier" in value:
                supplied_device_identifiers.append(value["DeviceIdentifier"])
            for child in value.values():
                validate_identifiers(child)
        elif isinstance(value, list):
            for child in value:
                validate_identifiers(child)

    validate_identifiers(parsed)
    if not set(supplied_device_identifiers).issubset(all_disk_set):
        raise ValueError("diskutil DeviceIdentifier contradicts AllDisks")
    return sorted(all_disks)


def _normalize_lines(payload: bytes) -> List[str]:
    return sorted(
        line.strip()
        for line in payload.decode("utf-8").splitlines()
        if line.strip()
    )


def collect_snapshot(
    *, runner=_run_command, serial_paths: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    raw_results: Dict[str, Dict[str, Any]] = {}
    command_status: Dict[str, Dict[str, Any]] = {}
    command_errors: Dict[str, str] = {}
    for name, command in COMMANDS.items():
        runner_error: Optional[str] = None
        try:
            result = runner(command)
        except Exception as exc:
            result = {
                "ok": False,
                "exit_code": None,
                "stdout": b"",
                "stderr": "",
            }
            runner_error = (
                "runner raised " + type(exc).__name__ + ": " + str(exc)
            )

        contract_errors: List[str] = []
        if not isinstance(result, dict):
            result = {}
            contract_errors.append("command runner result must be a dictionary")

        for required in ("ok", "exit_code", "stdout", "stderr"):
            if required not in result:
                contract_errors.append("command runner result is missing " + required)

        ok_value = result.get("ok")
        exit_code_value = result.get("exit_code")
        stdout_value = result.get("stdout")
        stderr_value = result.get("stderr")

        if type(ok_value) is not bool:
            contract_errors.append("command runner ok must be a boolean")
        if exit_code_value is not None and type(exit_code_value) is not int:
            contract_errors.append("command runner exit_code must be an integer or null")
        if type(stdout_value) is not bytes:
            contract_errors.append("command runner stdout must be bytes")
        if type(stderr_value) is not str:
            contract_errors.append("command runner stderr must be a string")

        if type(ok_value) is bool:
            if ok_value is True and exit_code_value != 0:
                contract_errors.append("successful command must have exit_code 0")
            if ok_value is False and exit_code_value == 0:
                contract_errors.append("failed command cannot have exit_code 0")

        stdout = stdout_value if type(stdout_value) is bytes else b""
        stderr = stderr_value if type(stderr_value) is str else ""
        if (
            name == "usb_ioreg"
            and ok_value is True
            and exit_code_value == 0
            and stdout == b""
            and stderr != ""
        ):
            contract_errors.append(
                "successful empty IORegistry output must have empty stderr"
            )

        if runner_error is not None:
            contract_errors.insert(0, runner_error)
        normalized_ok = ok_value is True and not contract_errors
        raw_results[name] = {"ok": normalized_ok, "stdout": stdout}
        if not normalized_ok:
            command_errors[name] = (
                "; ".join(contract_errors) if contract_errors else "command failed"
            )
        recorded_stderr = stderr
        if contract_errors:
            contract_text = "command contract: " + "; ".join(contract_errors)
            recorded_stderr = (
                recorded_stderr + " | " + contract_text
                if recorded_stderr
                else contract_text
            )
        command_status[name] = {
            "ok": normalized_ok,
            "exit_code": (
                exit_code_value
                if exit_code_value is None or type(exit_code_value) is int
                else None
            ),
            "stdout_bytes": len(stdout),
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr": recorded_stderr,
        }

    parse_errors: List[str] = []

    def parse(name: str, function, fallback):
        if not raw_results[name].get("ok"):
            parse_errors.append(name + ": " + command_errors[name])
            return fallback
        try:
            return function(raw_results[name]["stdout"])
        except Exception as exc:
            parse_errors.append(
                name + ": " + type(exc).__name__ + ": " + str(exc)
            )
            return fallback

    usb_ioreg = parse("usb_ioreg", _normalize_ioreg_usb_command_output, [])
    usb_profiler = parse("usb_system_profiler", _normalize_usb, [])
    usb_crosscheck_status = "NOT_CHECKED"
    if not any(
        error.startswith("usb_ioreg:") or error.startswith("usb_system_profiler:")
        for error in parse_errors
    ):
        try:
            _crosscheck_system_profiler_usb(usb_ioreg, usb_profiler)
        except Exception as exc:
            parse_errors.append(
                "usb_crosscheck: " + type(exc).__name__ + ": " + str(exc)
            )
            usb_crosscheck_status = "CONTRADICTION"
        else:
            if usb_profiler:
                usb_crosscheck_status = "SYSTEM_PROFILER_SUBSET_MATCH"
            elif usb_ioreg:
                usb_crosscheck_status = "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE"
            else:
                usb_crosscheck_status = "BOTH_EMPTY"
    hid = parse("hid", _normalize_hid, [])
    disks = parse("disks", _normalize_disks, [])
    interfaces = parse("interfaces", lambda data: data.decode("utf-8").split(), [])
    extensions = parse("system_extensions", _normalize_lines, [])

    if serial_paths is None:
        found = set()
        for pattern in ("/dev/cu.*", "/dev/tty.*"):
            found.update(glob.glob(pattern))
        serial_paths = sorted(found)

    normalized_serial_paths: List[str] = []
    if type(serial_paths) is not list:
        parse_errors.append("serial_paths: observation must be a list")
    elif not all(
        type(path) is str
        and re.fullmatch(r"/dev/(?:cu|tty)\.[^/\x00\r\n]+", path) is not None
        for path in serial_paths
    ):
        parse_errors.append(
            "serial_paths: entries must be exact non-empty /dev/cu.* or /dev/tty.* paths"
        )
    elif len(serial_paths) != len(set(serial_paths)):
        parse_errors.append("serial_paths: observation contains duplicate paths")
    else:
        normalized_serial_paths = sorted(serial_paths)

    complete = not parse_errors and all(item["ok"] for item in command_status.values())
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_utc": _utc_now(),
        "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "snapshot_complete": complete,
        "parse_errors": parse_errors,
        "commands": command_status,
        "usb_devices": usb_ioreg,
        "usb_enumeration": {
            "primary": "ioreg_IOUSBHostDevice",
            "crosscheck": "system_profiler_SPUSBDataType",
            "crosscheck_status": usb_crosscheck_status,
            "ioreg_device_count": len(usb_ioreg),
            "system_profiler_device_count": len(usb_profiler),
        },
        "hid_devices": hid,
        "disk_identifiers": sorted(set(disks)),
        "network_interfaces": sorted(set(interfaces)),
        "system_extension_lines": sorted(set(extensions)),
        "serial_paths": normalized_serial_paths,
        "evidence_boundary": (
            "Logical macOS enumeration snapshot only. USB identities come primarily from "
            "IORegistry and are cross-checked against any identities system_profiler reports. "
            "This does not authenticate USB firmware, prevent HID actions after approval, "
            "or establish electrical safety."
        ),
    }


def default_policy() -> Dict[str, Any]:
    return {
        "schema": POLICY_SCHEMA,
        "allowed_new_usb_fingerprints": [],
        "allowed_new_serial_path_regexes": [],
        "forbid_new_hid": True,
        "forbid_new_disks": True,
        "forbid_new_network_interfaces": True,
        "forbid_system_extension_changes": True,
        "note": (
            "Template intentionally allows no new USB device. Populate only after "
            "reviewing a cable-only, F100-disconnected discovery delta."
        ),
    }


def _new_by_fingerprint(
    before: Sequence[Dict[str, Any]], after: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return a multiset delta, preserving duplicate descriptor identities."""
    remaining = Counter(item.get("fingerprint_sha256") for item in before)
    new_items: List[Dict[str, Any]] = []
    for item in after:
        fingerprint = item.get("fingerprint_sha256")
        if remaining[fingerprint] > 0:
            remaining[fingerprint] -= 1
        else:
            new_items.append(item)
    return new_items


def _validate_snapshot_shape(name: str, snapshot: Dict[str, Any]) -> None:
    if not isinstance(snapshot.get("snapshot_complete"), bool):
        raise ValueError(f"{name}.snapshot_complete must be boolean")
    device_fields = ("usb_devices", "hid_devices")
    string_fields = (
        "disk_identifiers",
        "network_interfaces",
        "system_extension_lines",
        "serial_paths",
    )
    for field in device_fields:
        values = snapshot.get(field)
        if not isinstance(values, list):
            raise ValueError(f"{name}.{field} must be a list")
        for item in values:
            if not isinstance(item, dict) or not isinstance(
                item.get("fingerprint_sha256"), str
            ):
                raise ValueError(
                    f"{name}.{field} entries must be objects with string fingerprints"
                )
    for field in string_fields:
        values = snapshot.get(field)
        if not isinstance(values, list) or not all(
            type(item) is str and bool(item) for item in values
        ):
            raise ValueError(f"{name}.{field} must be a list of non-empty strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{name}.{field} must not contain duplicates")
    for path in snapshot["serial_paths"]:
        if re.fullmatch(r"/dev/(?:cu|tty)\.[^/\x00\r\n]+", path) is None:
            raise ValueError(f"{name}.serial_paths contains an invalid device path")

    usb_devices = snapshot["usb_devices"]
    enumeration = snapshot.get("usb_enumeration")
    if not isinstance(enumeration, dict):
        raise ValueError(f"{name}.usb_enumeration must be an object")
    if enumeration.get("primary") != "ioreg_IOUSBHostDevice":
        raise ValueError(f"{name}.usb_enumeration primary source is invalid")
    if enumeration.get("crosscheck") != "system_profiler_SPUSBDataType":
        raise ValueError(f"{name}.usb_enumeration crosscheck source is invalid")
    status = enumeration.get("crosscheck_status")
    allowed_statuses = {
        "BOTH_EMPTY",
        "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE",
        "SYSTEM_PROFILER_SUBSET_MATCH",
        "CONTRADICTION",
        "NOT_CHECKED",
    }
    if status not in allowed_statuses:
        raise ValueError(f"{name}.usb_enumeration crosscheck status is invalid")
    ioreg_count = enumeration.get("ioreg_device_count")
    profiler_count = enumeration.get("system_profiler_device_count")
    if (
        isinstance(ioreg_count, bool)
        or not isinstance(ioreg_count, int)
        or ioreg_count < 0
        or isinstance(profiler_count, bool)
        or not isinstance(profiler_count, int)
        or profiler_count < 0
    ):
        raise ValueError(f"{name}.usb_enumeration counts are invalid")
    if ioreg_count != len(usb_devices):
        raise ValueError(
            f"{name}.usb_enumeration IORegistry count does not match devices"
        )
    if status == "BOTH_EMPTY" and (ioreg_count != 0 or profiler_count != 0):
        raise ValueError(f"{name}.usb_enumeration BOTH_EMPTY counts are inconsistent")
    if status == "SYSTEM_PROFILER_EMPTY_IOREG_ACTIVE" and not (
        ioreg_count > 0 and profiler_count == 0
    ):
        raise ValueError(
            f"{name}.usb_enumeration empty-profiler counts are inconsistent"
        )
    if status == "SYSTEM_PROFILER_SUBSET_MATCH" and not (
        profiler_count > 0 and ioreg_count >= profiler_count
    ):
        raise ValueError(f"{name}.usb_enumeration subset counts are inconsistent")
    if snapshot["snapshot_complete"] and status in {"CONTRADICTION", "NOT_CHECKED"}:
        raise ValueError(
            f"{name}.snapshot_complete contradicts USB crosscheck status"
        )


def evaluate(before: Dict[str, Any], after: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    for name, value, schema in (
        ("before", before, SNAPSHOT_SCHEMA),
        ("after", after, SNAPSHOT_SCHEMA),
        ("policy", policy, POLICY_SCHEMA),
    ):
        if value.get("schema") != schema:
            raise ValueError(f"{name} has unsupported schema")
    _validate_snapshot_shape("before", before)
    _validate_snapshot_shape("after", after)

    new_usb = _new_by_fingerprint(before.get("usb_devices", []), after.get("usb_devices", []))
    new_hid = _new_by_fingerprint(before.get("hid_devices", []), after.get("hid_devices", []))
    removed_usb = _new_by_fingerprint(after.get("usb_devices", []), before.get("usb_devices", []))
    removed_hid = _new_by_fingerprint(after.get("hid_devices", []), before.get("hid_devices", []))
    new_disks = sorted(set(after.get("disk_identifiers", [])) - set(before.get("disk_identifiers", [])))
    removed_disks = sorted(set(before.get("disk_identifiers", [])) - set(after.get("disk_identifiers", [])))
    new_interfaces = sorted(set(after.get("network_interfaces", [])) - set(before.get("network_interfaces", [])))
    removed_interfaces = sorted(set(before.get("network_interfaces", [])) - set(after.get("network_interfaces", [])))
    new_serial = sorted(set(after.get("serial_paths", [])) - set(before.get("serial_paths", [])))
    removed_serial = sorted(set(before.get("serial_paths", [])) - set(after.get("serial_paths", [])))
    before_ext = set(before.get("system_extension_lines", []))
    after_ext = set(after.get("system_extension_lines", []))
    extension_changes = sorted(before_ext.symmetric_difference(after_ext))

    violations: List[str] = []
    if not before.get("snapshot_complete"):
        violations.append("before snapshot is incomplete")
    if not after.get("snapshot_complete"):
        violations.append("after snapshot is incomplete")

    allowed_usb_value = policy.get("allowed_new_usb_fingerprints", [])
    regex_value = policy.get("allowed_new_serial_path_regexes", [])
    if not isinstance(allowed_usb_value, list) or not all(
        isinstance(value, str) for value in allowed_usb_value
    ):
        raise ValueError("allowed_new_usb_fingerprints must be a list of strings")
    if not isinstance(regex_value, list) or not all(
        isinstance(value, str) for value in regex_value
    ):
        raise ValueError("allowed_new_serial_path_regexes must be a list of strings")
    for field in (
        "forbid_new_hid",
        "forbid_new_disks",
        "forbid_new_network_interfaces",
        "forbid_system_extension_changes",
    ):
        if not isinstance(policy.get(field), bool):
            raise ValueError(f"{field} must be boolean")

    allowed_usb = set(allowed_usb_value)
    for device in new_usb:
        fingerprint = device.get("fingerprint_sha256")
        if fingerprint not in allowed_usb:
            violations.append("new USB fingerprint is not allowlisted: " + str(fingerprint))

    regexes = []
    for expression in regex_value:
        try:
            regexes.append(re.compile(expression))
        except re.error as exc:
            raise ValueError("invalid serial path regex: " + str(exc))
    for path in new_serial:
        if not any(pattern.fullmatch(path) for pattern in regexes):
            violations.append("new serial path is not allowlisted: " + path)

    if policy.get("forbid_new_hid", True) and new_hid:
        violations.append(f"new HID devices observed: {len(new_hid)}")
    if policy.get("forbid_new_disks", True) and new_disks:
        violations.append("new disk identifiers observed: " + ", ".join(new_disks))
    if policy.get("forbid_new_network_interfaces", True) and new_interfaces:
        violations.append("new network interfaces observed: " + ", ".join(new_interfaces))
    if policy.get("forbid_system_extension_changes", True) and extension_changes:
        violations.append("system extension listing changed")
    if removed_usb:
        violations.append(f"USB devices disappeared from the baseline: {len(removed_usb)}")
    if removed_hid:
        violations.append(f"HID devices disappeared from the baseline: {len(removed_hid)}")
    if removed_disks:
        violations.append("disk identifiers disappeared from the baseline: " + ", ".join(removed_disks))
    if removed_interfaces:
        violations.append("network interfaces disappeared from the baseline: " + ", ".join(removed_interfaces))
    if removed_serial:
        violations.append("serial paths disappeared from the baseline: " + ", ".join(removed_serial))

    status = "PASS" if not violations else "FAIL"
    report = {
        "schema": REPORT_SCHEMA,
        "generated_utc": _utc_now(),
        "status": status,
        "violations": violations,
        "delta": {
            "new_usb_devices": new_usb,
            "new_hid_devices": new_hid,
            "new_disk_identifiers": new_disks,
            "new_network_interfaces": new_interfaces,
            "new_serial_paths": new_serial,
            "removed_usb_devices": removed_usb,
            "removed_hid_devices": removed_hid,
            "removed_disk_identifiers": removed_disks,
            "removed_network_interfaces": removed_interfaces,
            "removed_serial_paths": removed_serial,
            "system_extension_changes": extension_changes,
        },
        "badusb_prevention_claim": False,
        "safe_to_forward_automatically": False,
        "manual_review_required_even_on_pass": True,
        "inputs": {
            "before_snapshot_sha256": _canonical_hash(before),
            "after_snapshot_sha256": _canonical_hash(after),
            "policy_sha256": _canonical_hash(policy),
        },
        "evidence_boundary": (
            "PASS means observed additions matched this policy and no baseline "
            "USB/HID/disk/network/serial identity disappeared. It does not "
            "authenticate firmware or guarantee that an approved HID could not act."
        ),
    }
    report["report_sha256_without_this_field"] = _canonical_hash(report)
    return report


def _load_json(path: Path) -> Dict[str, Any]:
    value = _load_unique_json(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(str(path) + " is not a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="F100 Mac USB admission snapshot tool (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = sub.add_parser("snapshot", help="Record a read-only macOS device snapshot")
    snapshot_parser.add_argument("--output", type=Path, required=True)
    policy_parser = sub.add_parser("policy-template", help="Write a deny-by-default policy template")
    policy_parser.add_argument("--output", type=Path, required=True)
    evaluate_parser = sub.add_parser("evaluate", help="Compare two snapshots under an explicit policy")
    evaluate_parser.add_argument("--before", type=Path, required=True)
    evaluate_parser.add_argument("--after", type=Path, required=True)
    evaluate_parser.add_argument("--policy", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "snapshot":
            snapshot = collect_snapshot()
            _write_new_json(args.output, snapshot)
            print(json.dumps({"output": str(args.output), "snapshot_complete": snapshot["snapshot_complete"]}, indent=2))
            return 0 if snapshot["snapshot_complete"] else 2
        if args.command == "policy-template":
            _write_new_json(args.output, default_policy())
            print(str(args.output))
            return 0
        if args.command == "evaluate":
            report = evaluate(_load_json(args.before), _load_json(args.after), _load_json(args.policy))
            _write_new_json(args.output, report)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["status"] == "PASS" else 3
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
