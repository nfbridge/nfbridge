# Neo Film Bridge v0.7.2 preview r10 — FTDI adapter support, USB↔serial ancestry hardening, connection-guidance fixes

This release is minimal maintenance, not a new feature: it widens physical-hardware support and hardens a design weakness in cable admission found while doing so.

[한국어](RELEASE_NOTES.md)

## Wider adapter support

The cable admission check's eligible adapters widened from **the Prolific PL2303 (067B:2303) exact pair alone** to **two vendor families: Prolific (vendor ID `0x067b`) and FTDI (vendor ID `0x0403`)**.

The connection path is:

```
Nikon F100
→ Nikon MC-31 (RS-232 data cable)
→ an FTDI-based Serial-to-USB adapter (or a Prolific adapter)
→ Mac
```

The MC-31 and the Serial-to-USB adapter are two distinct devices — the MC-31 itself is not a USB device; macOS and this app observe and verify the adapter as the USB identity. The physically measured FTDI values are vendor ID `0x0403`, product ID `0x6001`; a specific manufacturer's individual brand name is not used as a supported-product name — it is described generically as an "FTDI-based Serial-to-USB adapter."

**A vendor match is not final approval or automatic trust — it is only the precondition for entering the admission procedure.** Everything after the vendor match is the same unweakened fail-closed verification as before: before/after USB snapshot comparison, fingerprint sealing, topology binding, the user's explicit physical confirmation, comparing the current reconnection against the registered approval, stopping on any unrelated USB change, and the existing network-isolation exception scope. Other USB-serial chipsets (CH340/CH341, CP210x, etc.) remain unsupported, and the vendor allowlist itself was not removed — there is no current real usage need beyond the Prolific and FTDI paths.

## USB↔serial ancestry hardening

While adding FTDI support, whether the vendor allowlist itself is a necessary security boundary was independently audited. The vendor check turned out not to be a real barrier against an attacker who deliberately forges vendor_id — and the audit also found a genuine defect in the existing admission design: the pipeline inferred "one new USB device + one new `/dev/cu.*` path" means the same physical device purely by **counting**, without any IOKit registry evidence that the serial path actually originated from the candidate USB device.

Comparing real IORegistry evidence collected separately from both physical adapters (Prolific and FTDI) showed both share the same class ancestry chain:

```
IOUSBHostDevice → IOUSBHostInterface → IOUserSerial → IOSerialBSDClient
```

(Only the `IOUserSerial` driver name differs — `AppleUSBPLCOM` for Prolific, `AppleUSBFTDI` for FTDI — the class is common, and the security decision does not depend on this driver/vendor string.) During the investigation, a real macOS behavior was confirmed empirically: querying `IOSerialBSDClient` as a descendant of `ioreg -a -r -c IOUSBHostDevice` can omit its `IOCalloutDevice`/`IODialinDevice` properties. A separate read-only command (`ioreg -a -r -c IOSerialBSDClient`) was added and correlated with the USB tree via `IORegistryEntryID`. This hardening-only collector never opens a serial port, never runs the F100 protocol, and never sends any command to the camera.

Based on this, the following invariant was added: **a candidate `/dev/cu.*` path must resolve, via `IORegistryEntryID`, to an `IOSerialBSDClient` node that is actually a descendant of the candidate USB device.** None of the pre-existing checks (snapshot diff, fingerprint, topology, user confirmation, reconnect validation, etc.) were loosened or removed — this is an additive check layered on top.

## Real-hardware re-test (2026-09-17)

The hardened admission path was re-tested against real Prolific and FTDI adapters, connected one at a time, using read-only import only (no EP/NP/erase).

| | Prolific | FTDI |
| --- | --- | --- |
| VID:PID | `0x067b:0x2303` | `0x0403:0x6001` |
| Ancestry check | PASS | PASS |
| Reconnect check | 4/4 `MATCHED_PREVIOUS_CABLE` | 3/3 `MATCHED_PREVIOUS_CABLE` |
| Read-only F100 communication | succeeded | succeeded |

Reconnect validation passed 7/7 in total, and both adapter families succeeded at real, read-only F100 communication. At the time of this test the F100's shooting-record memory had already been deliberately erased, so the successful result is `mode: "detailed"` (recording enabled), `roll_count: 0, rolls: []` — an empty-but-valid result that was correctly recognized, not mistaken for an error.

Across the 7 reconnect+read attempts, 3 hit `MQ: no response within 40s`. The precise scope: not an admission, ancestry, or reconnect failure — those sessions' admission records still show `MATCHED_PREVIOUS_CABLE`; the failure was in the later live serial I/O, waiting for an MQ response. In those attempts, the F100 was confirmed to have been powered on later than the guidance called for, which matches the symptom — but this observation alone is not treated as a confirmed protocol or timeout defect, and the cause is not overstated as user error either. **No communication code, timeout value, or retry logic was changed in this release.**

## Connection-guidance fixes

Two connection-order points that could cause confusion, found during the physical re-test, were fixed in wording only (no change to logic, timing, or protocol):

1. **First USB connection**: connect the USB end → if macOS asks to allow the accessory, allow it first → confirm the connection finished → only then click Yes → the camera end is still not connected. This order is now stated explicitly.
2. **F100 power-on**: connect the cable with the F100 off → turn the F100 on → confirm it is on → only then click Yes. This order is now stated explicitly. The previous wording allowed clicking Yes before actually powering the F100 on, matching the MQ-timeout attempts above.

No sleep/polling delay was added, no macOS security prompt was bypassed or auto-answered, and no explicit user confirmation step was removed. The Korean and English guidance carry the same meaning.

## Limits of what was verified

- Prolific PL2303 (067B:2303): prior physical-verification history, plus this round's read-only ancestry/reconnect re-test.
- An FTDI-based adapter (0403:6001) with a genuine MC-31: both the earlier read+erase physical test and this round's read-only ancestry/reconnect re-test are complete.
- Widening the Prolific 0x067b vendor family beyond 067B:2303, and other FTDI products (e.g. FT230X): **offline verification only** — no individual physical testing.
- Other chipsets (CH340/CH341, CP210x, etc.): still unsupported, not evaluated in this release.

## Camera command layer

The F100 read protocol, EP/NP/DP write commands, shooting-data decoding, export and HTML reporting were not touched by this change.

## Offline regression

- `tests/`: 166 PASS
- `mac-connection/`: 57 PASS
- `mac-client/`: 95 PASS, 1 SKIP (a pre-existing, unrelated skip because the research-only cable ID assistant is excluded from the public source package)
- Repository-wide Python compile check: passed
- Golden comparisons (`empty_roll`/`simple_one_roll`/`detailed_two_rolls`): 3/3 passed
- `MANIFEST.sha256`: 115/115 passed

## Support scope

The executable targets Apple Silicon and declares macOS 14.0 as its minimum. The app is ad-hoc signed, not Apple-notarized — this status is unchanged by this release.
