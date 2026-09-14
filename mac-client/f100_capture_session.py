#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed capture artifacts for the pre-hardware F100 Mac client.

This module records what the client asked the operating system to write and
what read() returned.  It is user-space API evidence, not wire timing,
electrical evidence, hardware validation, or proof of Nikon conformance.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


SCHEMA = "f100-mac-capture/0.1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CaptureSession:
    """One immutable directory containing JSONL, raw directions, and manifest."""

    def __init__(
        self,
        directory: Union[str, Path],
        *,
        port: str,
        command: str,
        serial_config: Dict[str, Any],
        integration: Optional[Dict[str, Any]] = None,
        operation_scope: str = "read-only",
    ) -> None:
        if operation_scope not in ("read-only", "erase-and-detailed", "record-settings", "erase-records"):
            raise ValueError("Unsupported capture operation scope")
        if operation_scope in ("record-settings", "erase-records"):
            import sys
            connection_dir = str(Path(__file__).resolve().parents[1] / "mac-connection")
            if connection_dir not in sys.path:
                sys.path.insert(0, connection_dir)
            from f100_operation_scope import validate
            if command != operation_scope or not isinstance(integration, dict):
                raise ValueError("Capture command/scope mismatch")
            validate(integration.get("operation"), command)
            if integration.get("command") != command or integration.get("operation_scope") != command:
                raise ValueError("Capture integration scope mismatch")
        self.operation_scope = operation_scope
        requested = Path(directory).expanduser()
        if requested.name in ("", ".", ".."):
            raise ValueError("capture directory must name a new child directory")
        parent = requested.parent.resolve(strict=True)
        if not parent.is_dir():
            raise ValueError("capture directory parent is not a directory")
        self.directory = parent / requested.name
        if self.directory.exists() or self.directory.is_symlink():
            raise FileExistsError(
                "capture directory already exists; refusing to overwrite evidence: "
                + str(self.directory)
            )
        self.directory.mkdir(mode=0o700)
        os.chmod(self.directory, 0o700)

        self.port = port
        self.command = command
        self.serial_config = dict(serial_config)
        self.integration = dict(integration or {})
        self.started_utc = _utc_now()
        self._started_monotonic_ns = time.monotonic_ns()
        self._sequence = 0
        self._call_id = 0
        self._finished = False
        self._tx_bytes = 0
        self._rx_bytes = 0
        self._tx_short_writes = 0
        self._tx_exceptions = 0
        self._rx_exceptions = 0

        self.events_path = self.directory / "events.jsonl"
        self.tx_path = self.directory / "host-to-camera.bin"
        self.rx_path = self.directory / "camera-to-host.bin"
        self.manifest_path = self.directory / "session-manifest.json"
        self._events = self.events_path.open("x", encoding="utf-8", newline="\n")
        self._tx = self.tx_path.open("xb")
        self._rx = self.rx_path.open("xb")
        self.record(
            "session_start",
            schema=SCHEMA,
            port=port,
            command=command,
            serial_config=self.serial_config,
            integration=self.integration,
            evidence_boundary="user-space serial API calls; not wire or electrical timing",
        )

    def record(self, event: str, **fields: Any) -> int:
        if self._finished:
            raise RuntimeError("capture session is already finished")
        self._sequence += 1
        item: Dict[str, Any] = {
            "sequence": self._sequence,
            "event": event,
            "wall_time_utc": _utc_now(),
            "monotonic_ns_since_start": (
                time.monotonic_ns() - self._started_monotonic_ns
            ),
        }
        item.update(fields)
        self._events.write(
            json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        )
        self._events.flush()
        return self._sequence

    def tx_attempt(self, data: bytes, *, role: str, opcode: Optional[str]) -> int:
        self._call_id += 1
        call_id = self._call_id
        self.record(
            "tx_attempt",
            call_id=call_id,
            role=role,
            opcode=opcode,
            requested_bytes=len(data),
            payload_hex=data.hex(),
        )
        return call_id

    def tx_result(
        self,
        call_id: int,
        data: bytes,
        transferred: int,
        *,
        role: str,
        opcode: Optional[str],
    ) -> None:
        if transferred < 0 or transferred > len(data):
            raise ValueError("transferred byte count is outside the request")
        actual = data[:transferred]
        self._tx.write(actual)
        self._tx.flush()
        self._tx_bytes += transferred
        if transferred != len(data):
            self._tx_short_writes += 1
        self.record(
            "tx_result",
            call_id=call_id,
            role=role,
            opcode=opcode,
            requested_bytes=len(data),
            transferred_bytes=transferred,
            complete=(transferred == len(data)),
        )

    def tx_exception(
        self,
        call_id: int,
        exc: BaseException,
        *,
        role: str,
        opcode: Optional[str],
    ) -> None:
        self._tx_exceptions += 1
        self.record(
            "tx_exception",
            call_id=call_id,
            role=role,
            opcode=opcode,
            exception_type=type(exc).__name__,
            message=str(exc),
        )

    def rx(self, data: bytes, *, opcode: str) -> None:
        self._rx.write(data)
        self._rx.flush()
        self._rx_bytes += len(data)
        self.record(
            "rx_result",
            opcode=opcode,
            transferred_bytes=len(data),
            payload_hex=data.hex(),
        )

    def read_exception(self, exc: BaseException, *, opcode: str) -> None:
        self._rx_exceptions += 1
        self.record(
            "rx_exception",
            opcode=opcode,
            exception_type=type(exc).__name__,
            message=str(exc),
        )

    def finish(self, outcome: str, error: Optional[str] = None) -> Path:
        if self._finished:
            return self.manifest_path
        if outcome not in ("success", "failure", "interrupted"):
            raise ValueError("invalid capture outcome")
        self.record("session_end", outcome=outcome, error=error)
        sequence_count = self._sequence
        for handle in (self._events, self._tx, self._rx):
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        self._finished = True

        manifest: Dict[str, Any] = {
            "schema": SCHEMA,
            "generated_utc": _utc_now(),
            "started_utc": self.started_utc,
            "outcome": outcome,
            "error": error,
            "command": self.command,
            "port": self.port,
            "serial_config": self.serial_config,
            "integration": self.integration,
            "event_count": sequence_count,
            "events_file": self.events_path.name,
            "events_bytes": self.events_path.stat().st_size,
            "events_sha256": _sha256(self.events_path),
            "host_to_camera_file": self.tx_path.name,
            "host_to_camera_bytes": self._tx_bytes,
            "host_to_camera_sha256": _sha256(self.tx_path),
            "camera_to_host_file": self.rx_path.name,
            "camera_to_host_bytes": self._rx_bytes,
            "camera_to_host_sha256": _sha256(self.rx_path),
            "tx_short_write_count": self._tx_short_writes,
            "tx_exception_count": self._tx_exceptions,
            "rx_exception_count": self._rx_exceptions,
            "api_byte_reconstruction_complete": (
                self._tx_short_writes == 0
                and self._tx_exceptions == 0
                and self._rx_exceptions == 0
            ),
            "evidence_class": "UNVALIDATED_USER_SPACE_SERIAL_API_OBSERVATION",
            "observer_initiates_serial_io": True,
            "target_write_prevention_supported": False,
            "hardware_validation": "NOT_PERFORMED",
            "live_hardware_validation": False,
            "live_safe_claim": False,
            "nikon_specification_match_claim": False,
            "np_dp_ep_implemented": self.operation_scope != "read-only",
            "operation_scope": self.operation_scope,
            "dp_implemented": False,
            "lq_default_live_blocked": True,
            "evidence_boundary": (
                "Records client write requests/results and bytes returned by read(); "
                "a write exception may occur after an unknowable partial OS/device transfer; "
                "does not establish wire timing, voltage, polarity, camera behavior, "
                "live safety, or Nikon specification conformance."
            ),
        }
        temporary = self.directory / ".session-manifest.json.tmp"
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.manifest_path)
        return self.manifest_path
