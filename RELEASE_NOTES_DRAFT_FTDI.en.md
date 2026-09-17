# Neo Film Bridge v0.7.2-preview-r10 (draft) — Expanded USB-serial adapter support

> **This is a draft.** No tag or GitHub Release has been created yet, and nothing has been committed or pushed. This document is for review; once approved it will be published as-is or lightly edited.

This release is minimal maintenance for wider physical-hardware testing, not a new feature.

## A. Changes

The cable admission check's eligible adapters widened from **the Prolific PL2303 (067B:2303) exact pair alone** to **two vendor families: Prolific (vendor ID `0x067b`) and FTDI (vendor ID `0x0403`)**.

The connection path is:

```
Nikon F100
→ Nikon MC-31 (RS-232 data cable)
→ supported Serial-to-USB adapter
→ Mac
```

The MC-31 and the USB-serial adapter are two distinct devices — the MC-31 itself is not authenticated as a USB device; macOS and this app observe the adapter as the USB device.

**A vendor match is not final approval or automatic trust — it is only the precondition for entering the admission procedure.** Everything after the vendor match is the same unweakened fail-closed verification as before: before/after USB snapshot comparison, detecting a new USB device and a new `/dev/cu.*` serial path and checking its correctness and uniqueness, fingerprint sealing, topology binding, the user's explicit physical confirmation, comparing a registered approval against the current reconnection and stopping on any mismatch, stopping on any unrelated USB change, stopping on an incomplete snapshot, and the existing scope of the network-isolation exception. Precise summary: **adding and unifying the Prolific and FTDI vendor families as eligible to enter admission widens the pre-approval scope, but none of the fail-closed conditions after admission were loosened.**

Whether this vendor allowlist is itself a necessary security boundary was independently audited. Conclusion: the vendor check is not a real barrier against a deliberate attacker, who can freely set vendor_id/product_id in firmware — the actual defenses all come from vendor-independent downstream checks (snapshot diff, fingerprint, topology, user confirmation). The audit did find a genuine, pre-existing design gap: the pipeline infers that a new USB device and a new `/dev/cu.*` path are the same physical device purely by count ("exactly one of each"), with no IOKit registry evidence tying the specific serial node to the specific USB device subtree (see the regression tests in `mac-connection/test_f100_offline_usb_gate.py::VendorAllowlistSecurityAuditTests`). This gap predates r10 and is unaffected by keeping or removing the vendor allowlist; removing the allowlist would not close it. The current Prolific/FTDI (067b/0403) policy is therefore kept as-is — not generalized — until that binding is hardened.

Other USB-serial chipsets (CH340/CH341, CP210x, etc.) remain unsupported. Being a supported vendor never grants automatic approval on its own; the user must still complete the full "Re-check cable" flow.

Guidance text changed from the Prolific-only "this guide is for the tested Prolific F100 data cable" wording to "a supported USB-serial adapter (Prolific PL2303 or the FTDI family)". The first-connection guidance was also clarified to state the order explicitly: (1) connect the USB end → (2) if macOS asks to allow the accessory to connect, allow it first → (3) wait for the device to finish connecting → (4) then proceed in the app window → (5) the camera end is still not connected at this point. No arbitrary sleep or delay was added.

## B. Physical test on 2026-09-17

Real communication was performed on developer-owned hardware through Nikon F100 → genuine Nikon MC-31 RS-232 data cable → an FTDI-based Serial-to-USB adapter → Apple Silicon Mac.

Confirmed results:
- FTDI admission succeeded (admission report `PASS`, forwarding gate `PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW`)
- Camera connection succeeded
- Roll 46, 25 frames, imported successfully
- Camera-record erasure succeeded (`outcome: success`)

**A successful erase is not the same as a successful EP/NP settings write.** The write operation verified in this physical test was erase (EP); a recording-settings change (NP) was not separately physically tested.

## C. Limits of what was verified

- The existing Prolific PL2303 (067B:2303) path: already had a prior physical-verification history.
- An FTDI-based adapter with a genuine MC-31: physically verified on 2026-09-17 with the configuration above.
- Widening the Prolific 0x067b vendor family beyond 067B:2303: **offline verification only** in this change; no individual physical testing was done for other Prolific product IDs.
- Other FTDI products (e.g. FT230X): being eligible for vendor-family admission is a different claim from having been individually physically tested — only one FT232R-family product has been physically tested.

## D. Camera command layer

The F100 read protocol, EP/NP/DP write commands, shooting-data decoding, export and HTML reporting were not touched by this change. Only the USB cable admission check and its related guidance text, documentation and tests were modified.

## E. Offline regression

Final re-run of the r10 candidate changes (including the PHASE 1–3 USB↔serial ancestry hardening and this round's connection-guidance UX fixes) in the current working tree:

- `tests/`: 166 PASS (162 before this round, plus 4 new tests verifying the connection-guidance wording's meaning)
- `mac-connection/`: 57 PASS (up from 44, including PHASE 2 ancestry-hardening regressions)
- `mac-client/`: 95 PASS, 1 SKIP (`test_cable_id_cli_uses_shared_identification_without_serial_access` — a pre-existing, unrelated skip because the research-only cable ID assistant is excluded from the public source package)
- Total: **318 PASS / 0 FAIL / 1 pre-existing, unrelated SKIP**
- Repository-wide Python compile check: passed
- `MANIFEST.sha256`: dates from the r9 commit, so it expectedly mismatches on the 18 files this r10 round changed (both READMEs, app/camera.py, connection.py, i18n.py, nfbridge.py, docs/VALIDATION.md, 6 PHASE 2 ancestry-hardening files under mac-connection, 3 test files, and the pre-existing unrelated uncommitted change to RELEASE_CHECKLIST.md) — it will be regenerated when this is actually committed. No unexpected file mismatched.
- Golden comparisons (`empty_roll`/`simple_one_roll`/`detailed_two_rolls`): 3/3 passed

## F. Support scope

The executable targets Apple Silicon and declares macOS 14.0 as its minimum. The app is ad-hoc signed, not Apple-notarized — this status is unchanged by this release.

## G. USB↔serial ancestry hardening and real-hardware re-test

While auditing whether the vendor allowlist itself is a necessary security boundary (section A), a genuine pre-existing design gap was found and then actually hardened: the pipeline previously inferred "same physical device" purely from counting a new USB device plus a new `/dev/cu.*` path, with no IOKit registry evidence behind it.

Comparing real IORegistry evidence collected separately from both physical adapters (Prolific and FTDI) showed both share the same class ancestry chain:

```
IOUSBHostDevice → IOUSBHostInterface → IOUserSerial → IOSerialBSDClient
```

(Only the `IOUserSerial` driver name differs — `AppleUSBPLCOM` vs `AppleUSBFTDI` — the class is common.) Based on this, a driver-name-independent check was added: a candidate `/dev/cu.*` path must resolve, via `IORegistryEntryID`, to an `IOSerialBSDClient` node that is actually a descendant of the candidate USB device (`f100_offline_usb_gate.py::_bind_candidate_serial_ancestry()`, wired into `connection.inspect()`/`connection.prepare()`). None of the pre-existing checks (snapshot diff, fingerprint, topology, user confirmation, reconnect validation, etc.) were loosened or removed — this is additive.

This hardening was then re-verified against real hardware (read-only import only; no EP/NP/erase):

| | Prolific | FTDI |
| --- | --- | --- |
| VID:PID | `0x067b:0x2303` | `0x0403:0x6001` |
| `/dev/cu.*` | `/dev/cu.usbserial-1110` | `/dev/cu.usbserial-FTESX9JU` |
| Ancestry check | `candidate_serial_ancestry_verified: true` | `candidate_serial_ancestry_verified: true` |
| Reconnect check | 4/4 `MATCHED_PREVIOUS_CABLE` | 3/3 `MATCHED_PREVIOUS_CABLE` |
| Read-only communication | succeeded | succeeded |

At the time of this test the F100's shooting-record memory had already been deliberately erased, so the expected and observed successful result is `mode: "detailed"` (recording enabled), `roll_count: 0, rolls: []` — confirmed directly from the saved `shooting-data.json`, not just the on-screen message, as an empty-but-valid decode rather than an error.

Across 7 reconnect+read attempts, 3 hit `MQ: no response within 40s`. Those sessions' `report.json` still show `status: "MATCHED_PREVIOUS_CABLE"` — admission, ancestry and reconnect checks all passed; only the later live serial I/O timed out. The user confirmed that in some of the affected attempts the F100 was powered on later than the guidance called for, which matches the symptom. This evidence alone is not treated as a protocol or timeout defect, and **no communication or timeout code was changed.** Instead, the guidance wording below was clarified.

The vendor allowlist itself was not removed by this hardening (see section I).

## H. Connection-guidance wording fixes

Two connection-order sources of confusion found during the physical re-test were removed from the guidance wording only (no change to admission logic, snapshot timing, or serial-open timing):

1. **First USB connection**: the wording now states explicitly that macOS may ask to allow a new USB-serial accessory, that this must be resolved first, and that Yes should only be clicked in NFBridge after confirming the USB device finished connecting.
2. **F100 power-on**: the wording now states the order explicitly — connect the cable with the F100 off → turn the F100 on → confirm it is on → only then click Yes. The previous wording allowed clicking Yes before actually powering the F100 on, matching the pattern in the MQ-timeout sessions above.

No sleep/polling delay was added, no macOS security prompt was bypassed or auto-answered, and no explicit user confirmation step was removed.

## I. Vendor allowlist — final decision for r10

To resolve the open research direction (HARDEN_THEN_REMOVE) left in an earlier draft: **HARDEN is done (section G); REMOVE is not being pursued.** Current real usage only needs the Prolific and FTDI paths. Even though the ancestry hardening would likely let other vendors be safely screened too, that is not a reason to widen support in this release. Neither adding other chipsets (CH340/CH341, CP210x, ...) nor removing the vendor allowlist itself is in scope for r10. Ancestry hardening remains an independent, additive check alongside the vendor policy, not a replacement for it.

---

[한국어 초안](RELEASE_NOTES_DRAFT_FTDI.md)
