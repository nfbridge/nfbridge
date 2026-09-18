# Neo Film Bridge v0.7.2 preview r11 — F100 flash field decode correction

This release is minimal maintenance, not a new feature: it corrects the decoded accuracy of the flash-related fields in existing F100 shooting data, based on real-hardware evidence. Camera communication, connection admission, settings changes, and erase procedures are unchanged.

[한국어](RELEASE_NOTES.md)

## What changed

Two flash-related fields were corrected.

**Flash type**
- Before: only `off`/`ttl` were recognized. The bit mask itself was structurally misaligned, so a valid code could be misread as `unknown` depending on unrelated bits elsewhere in the same byte.
- Corrected: this is a 2-bit field. It now decodes `off`, `non_ttl` (Non-TTL), and `ttl` (TTL) from the correct bit range. The one remaining unobserved code stays `unknown`.

**Flash sync**
- Before: only `Normal` and `Rear` (rear-curtain) were recognized.
- Corrected: `Slow`, `Red-eye`, and `Red-eye + Slow` were added. Codes not confirmed to be produced by the camera stay `unknown` — they were not guessed or promoted.

Flash compensation (EV) and the multiple-exposure flag were re-confirmed to already match real values exactly; no code changed there.

## Real-hardware evidence

This correction was made only after directly reading two real F100-shot rolls' shooting data and cross-checking every frame's flash state (off/non-TTL/TTL, all five sync values, compensation, multiple exposure) against an independent separate reading of the same data, frame by frame. Nothing was guessed or reconstructed; only values actually observed were treated as ground truth.

## Note on a past documentation error

While re-confirming against real hardware, an earlier analysis record in this project's history was found to have the flash-type (TTL/Non-TTL) and flash-sync (Slow/Rear) labels swapped. The bit positions themselves were correct from the start — only the meaning assigned to each value was wrong. That earlier record was left as-is rather than rewritten retroactively; only the current code and documentation carry the corrected labels.

## Scope

- Camera communication, USB/serial connection admission, settings/erase procedures, app structure, and packaging: unchanged.
- The output JSON's field names, structure (schema), and value-provenance policy: unchanged — any external tool already reading this file is unaffected.

## Offline regression

- `tests/`: 168 PASS
- `mac-connection/`: 57 PASS
- `mac-client/`: 115 PASS, 1 SKIP (pre-existing, unrelated skip: a research-only cable-identification tool excluded from the public source package)
- Whole-repository Python compilation check: pass
- Golden comparisons (`empty_roll`/`simple_one_roll`/`detailed_two_rolls`): 3/3 pass
- `MANIFEST.sha256`: 114/114 verified

## Support scope

The executable targets Apple Silicon and declares macOS 14.0+. The app is ad-hoc signed and not Apple-notarized — unchanged by this release.
