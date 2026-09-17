# Validation record

On 2026-09-13 the upstream implementation completed direct macOS/F100 communication through Prolific 067B:2303 and AppleUSBPLCOM. DTR=True/RTS=False were requested before open; electrical line levels were not measured.

| Read | Result |
| --- | --- |
| MQ | Empty 79, one retry, 61 with 1A |
| OQ | Empty 79, one retry, 61 with 06 0A |
| LQ session | MQ 79 then 61; OQ 61; LQ 61 with 1547-byte payload |

The complete LQ frame was 1550 bytes. Payload SHA-256: `b9f86e8145f6a8db2a57fb847beba3543b70c79d1d1e907326747cdd6c9a957f`. It matched both Windows reference applications byte for byte. Independent decoding agreed on 1053/1053 compared fields (117 frames × 9). Raw captures remain in the private research archive and are not independently reproducible from this public package alone.

The public export is a derivative: personal fixed-adapter entry points, private evidence and external value tables are omitted. Included synthetic tests validate transport behavior and public functionality without hardware; they must not be described as replaying the private 117-frame capture.

Only this observed F100/adapter configuration has been established. Later GUI import,
recording-setting changes and erasure were also exercised on the developer-owned Mac/F100
with user confirmations (private project worklog §§232–234). On 2026-09-14, the
v0.7.1 disk-name fix was tried on an additional macOS 26.2 Mac: user-provided
screenshots show first-use connection followed by GUI import and save of one roll
with 12 frames, and the generated HTML table opened in a browser. The second
Mac's raw serial capture was not independently compared, and setting changes
or erasure were not tested there. Other adapters and a fresh-user installation
remain unverified.

## Formula-default update

Default decoding now works without external tables. An offline comparison against the preserved 117-frame payload matched 1053 fields after display normalization; no new live read was made for that comparison. See NUMERIC_DECODING.md. The package's offline tests and later GUI hardware observations are separate evidence.

## FTDI Serial-to-USB adapter admission

On 2026-09-17 the guided GUI cable check, import and erase flows were exercised end to end on the developer-owned Mac/F100 through **Nikon F100 → genuine Nikon MC-31 RS-232 data cable → an FTDI-based Serial-to-USB adapter (vendor 0x0403, product 0x6001, FT232R family) → Apple Silicon Mac**, in addition to the previously verified Prolific 067B:2303 path. The USB admission cable check recognized the FTDI adapter under the vendor-family entry added for FTDI support (see the FTDI admission handoff), required the same explicit "review cable" user confirmation as Prolific, and produced a `PASS` admission report and `PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW` forwarding gate. A subsequent read imported one roll (46) with 25 frames at ISO 250 from `camera_api_capture`. An erase-records operation completed with a single `EP` write, preceded by a saved-and-reverified backup, and with `outcome: success`. No other USB-serial chipset was added or tested.

Following this physical result, the same vendor-family reasoning was audited against Prolific (see the FTDI admission handoff): the admission pipeline's fail-closed checks — fingerprint sealing, topology binding, the requirement of exactly one new serial path, and explicit user confirmation — are unaffected by which vendor matched the eligibility pre-gate, so there was no safety or functional basis to keep Prolific pinned to the single tested 067B:2303 pair while FTDI was recognized at the vendor level. The policy was unified to admit both the Prolific (067B) and FTDI (0403) vendor families, verified with offline regression tests (see tests/test_guided.py::SupportedAdapterTests and tests/test_camera_service.py's `test_prolific_other_product_id_*` cases). Widening to other Prolific product IDs has not itself been physically tested with real hardware.

## Independent audit of the vendor/chipset allowlist itself

A separate, independent audit then asked whether the vendor allowlist above is itself a necessary security boundary, or a redundant pre-filter that could be removed or generalized. Probing `derive_candidate()`/`_bind_candidate_topology()` directly with `expected_vid`/`expected_pid` set to `None` (simulating no vendor pre-gate) showed that an unsupported or entirely unknown vendor reaches `REVIEW_REQUIRED` with zero violations exactly like a supported one — the real gate is downstream (snapshot diff, fingerprint sealing, topology self-consistency, explicit user confirmation, reconnect comparison), not the vendor check, and a deliberate attacker can set `vendor_id`/`product_id` to anything in firmware regardless of this allowlist.

The audit also found a genuine, pre-existing, vendor-independent design gap: the pipeline treats "exactly one new USB device" plus "exactly one new `/dev/cu.*` path" as the same physical device by count alone — there is no IOKit registry evidence (parent/child relationship, `IOCalloutDevice`/`IOSerialBSDClient` linkage, or similar) confirming the specific serial node actually originates from the specific USB device. A USB device with no name or topology suggesting it is a serial adapter, coincidentally paired with an unrelated new serial path, currently reaches `REVIEW_REQUIRED` with zero violations. The `/dev/cu.` prefix filter also does not distinguish a USB-originated path from a Bluetooth or other virtual one. These findings are recorded as regression tests in `mac-connection/test_f100_offline_usb_gate.py::VendorAllowlistSecurityAuditTests`, since removing the vendor allowlist does not create or worsen this gap — it already exists today.

Verdict: **HARDEN_THEN_REMOVE**. The vendor allowlist is not itself a security boundary against a deliberate attacker, but narrowing candidate vendors has some non-adversarial value (fewer coincidental unrelated devices can land in the weak USB↔serial binding above) until that binding is hardened with real registry-derived evidence. The 067B/0403 policy is kept unchanged rather than generalized to all USB-serial adapters.

## USB↔serial ancestry hardening (PHASE 2, 2026-09-17)

Before designing any fix, real IORegistry evidence was collected on the developer-owned Mac (macOS 26) from a physical Prolific adapter and a physical FTDI adapter **separately** (never both attached at once), using a new, read-only, offline evidence-collection tool (`mac-connection/collect_usb_serial_ancestry_evidence.py`) that never opens a serial port and never sends any command to the F100 or any device. Both adapters were found to share an identical IORegistry class ancestry chain from the USB device down to the serial node:

```
IOUSBHostDevice → IOUSBHostInterface → IOUserSerial → IOSerialBSDClient
```

The `IOUserSerial` node's `IORegistryEntryName` differs by driver (`AppleUSBPLCOM` for Prolific, `AppleUSBFTDI` for FTDI), but its **class** is common to both, and the terminal `IOSerialBSDClient` node (class name, not driver name) is what carries the actual `/dev/cu.*`/`/dev/tty.*` device-file properties (`IOCalloutDevice`/`IODialinDevice`), correlated back to its owning USB device subtree via `IORegistryEntryID`. This is the vendor-independent structural invariant the hardening implements: **a candidate `/dev/cu.*` serial path must resolve to an `IOSerialBSDClient` registry node whose `IORegistryEntryID` is present among the candidate USB device's own descendant `IOSerialBSDClient` nodes** — not inferred from device-count cardinality alone, as before.

Implementation: a new offline snapshot field `serial_bsd_clients` (collected via `ioreg -a -r -c IOSerialBSDClient`, snapshot schema bumped to `f100-usb-admission-snapshot/0.3`) plus per-device `serial_client_registry_ids`, and a new fail-closed check `f100_offline_usb_gate.py::_bind_candidate_serial_ancestry()`, called from both `connection.inspect()` and `connection.prepare()` immediately after the existing `_bind_candidate_topology()` check. It is additive: every pre-existing check (before/after snapshot diff, exactly-one-candidate-USB-device, exactly-one-candidate-serial-path, fingerprint sealing, topology self-consistency, user confirmation, reconnect validation, unrelated-USB/HID-change rejection, network-isolation exception scope, live transport authorization) is unchanged. Missing, ambiguous (e.g. two `IOSerialBSDClient` entries claiming the same device file), or mismatched (path traces to a different USB device's subtree) ancestry evidence forces `status=FAIL`; there is no first-match or guessing fallback. Registry entry IDs are excluded from both the fingerprint hash and the reconnect-equality comparison (`_enumeration_view()`), since IOKit assigns them fresh on every physical (re)connection and boot.

The hardening closed two previously-passing gap regressions in `VendorAllowlistSecurityAuditTests` (now renamed to assert `FAIL`: `test_unrelated_usb_device_and_unrelated_serial_path_now_fails_ancestry_binding`, `test_bluetooth_named_serial_path_now_fails_ancestry_binding`) and added three new tests: `test_verified_ancestry_still_passes` (positive control), `test_ancestry_pointing_at_a_different_device_fails`, `test_ambiguous_ancestry_with_duplicate_callout_device_fails`. Full offline regression after the change: `mac-connection/` 57/57, `mac-client/` 95/95 (1 pre-existing unrelated skip), `tests/` 162/162 — all passing, none relaxed to force a pass.

## USB↔serial ancestry hardening — real-hardware read-only re-test (PHASE 3, 2026-09-17)

The hardened admission path above was re-tested against real physical hardware through the actual guided GUI flow (`app/gui.py` / `app/camera.py`'s `enroll()`/`prepare()`, not offline fixtures), using an isolated `--home` per vendor. Camera writes (EP/NP/erase) were never sent; every test was a read-only `lq` import.

| | Prolific | FTDI |
| --- | --- | --- |
| VID:PID | `0x067b:0x2303` | `0x0403:0x6001` |
| `/dev/cu.*` port | `/dev/cu.usbserial-1110` | `/dev/cu.usbserial-FTESX9JU` |
| First admission | `REVIEW_REQUIRED`, no violations | `REVIEW_REQUIRED`, no violations |
| `candidate_serial_ancestry_verified` | `true` | `true` |
| Reconnect (`check_current`) | 4/4 `MATCHED_PREVIOUS_CABLE` | 3/3 `MATCHED_PREVIOUS_CABLE` |
| Read-only `lq` communication | succeeded | succeeded |

The actual real path exercised for the FTDI case was **Nikon F100 → genuine Nikon MC-31 (RS-232) → an FTDI-based Serial-to-USB adapter → Apple Silicon Mac**; MC-31 itself is not a USB device and is not part of the vendor/ancestry checks, which apply to the Serial-to-USB adapter.

At the time of this test the F100's shooting-record memory had already been deliberately erased by the user in an earlier session, so the expected and observed successful-read result is `mode: "detailed"` (recording enabled), `roll_count: 0`, `rolls: []` — an empty-but-valid decode, not an error. This was independently confirmed by reading the saved `shooting-data.json` for each successful session, not just from the on-screen message.

Across 7 total reconnect+read attempts (4 Prolific, 3 FTDI), 3 hit `f100_readonly.ProtocolError: MQ: no response within 40s` — an F100 serial-I/O timeout after admission/ancestry/reconnect had already succeeded (each of those sessions' `mac-admission/report.json` still shows `status: "MATCHED_PREVIOUS_CABLE"`). The user confirmed that in some of the affected attempts the F100 was powered on later than the connection guidance called for. Given this, the timeouts are **not** attributed to a protocol or timeout-value defect, and no communication-layer or timeout code was changed as a result. Two first-connection guidance strings were instead clarified (see below) so the required power-on order is harder to get out of sequence; this is a UX change, not a protocol change.

Ancestry binding and reconnect validation themselves had **zero** failures across all 9 sessions collected (2 first-time admissions + 7 reconnects) in this PHASE 3 run.

**PHASE 4** (re-evaluating whether the vendor allowlist can be removed now that ancestry binding is hardened and hardware-verified) was **not started**. There is no current user need for USB-serial vendors beyond Prolific and FTDI, so widening eligibility — even though the ancestry check would likely make it technically safer — is out of scope for this release. The vendor allowlist and the ancestry check remain two independent, additive layers; ancestry binding does not replace or supersede the vendor check.

## Connection-guidance UX fixes (r10 candidate, 2026-09-17)

Two ordering problems in the guided connection prompts were identified from the PHASE 3 real-hardware session and fixed (wording only — no change to admission logic, snapshot timing, or serial-open timing):

1. **USB-only step**: the previous wording asked the user to connect the adapter and proceed, without making explicit that macOS's own "allow this accessory" prompt (when a USB-serial adapter is new to this Mac) must be resolved *before* confirming in NFBridge — otherwise the `after` snapshot could in principle be collected before macOS finished enumerating the device. The prompt (`app/camera.py`'s `usb-only` text, `app/nfbridge.py`'s matching CLI prompt, and the `app/i18n.py` English translation) now states explicitly: allow the macOS accessory prompt first, and only click Yes / continue after confirming the USB device finished connecting.
2. **Camera power-on step**: the previous wording ("전원을 끈 상태에서 케이블을 연결한 뒤 전원을 켜세요... 준비됐나요?") did not prevent a user from clicking Yes before actually turning the F100 on. This matches the pattern observed in the PHASE 3 MQ-timeout sessions. The prompt (`app/camera.py`'s `connect-camera` text, `app/nfbridge.py`'s matching CLI prompt, and the English translation) now states the order explicitly — F100 off → connect cable → turn F100 on → confirm it is on → only then click Yes — and keeps the existing Windows VM / other-camera-program reminder.

No `sleep`/polling delay was added, no macOS security prompt is bypassed or auto-answered, and the user's explicit confirmation step was not removed — only the wording and required order were clarified. Regression coverage: `tests/test_i18n.py::test_usb_first_connect_guidance_orders_macos_allow_before_yes`, `::test_camera_power_on_guidance_orders_power_on_before_yes`, `tests/test_guided.py::ConnectionGuidanceOrderTests` (CLI wording).
