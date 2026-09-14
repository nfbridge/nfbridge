# mac-connection

This directory checks a cable and authorizes a **specific, user-initiated** camera operation. It does not run a background USB watcher. Camera commands and shooting-data decoding live in `../mac-client/`.

The v0.7 app uses `f100_usb_admission.py` and `f100_offline_usb_gate.py` to compare USB snapshots, `f100_orchestrator.py` to create a command-specific plan, and `f100_reconnect.py`, `f100_live_binding.py`, and `f100_operation_scope.py` to verify the registered cable, plan, and permitted operation before serial access. The GUI starts these checks only after a user action.

The former `f100_first_use_assistant.py`, `f100_preauth_gate.py`, and `f100_serial_relay.py` remain only in private research history. They are excluded from this public source and the v0.7 app bundle, along with their dedicated tests and the `cable-id` and Windows/relay plan modes. The active macOS connection checks remain. See [publication scope](../docs/PUBLICATION_SCOPE.md).
