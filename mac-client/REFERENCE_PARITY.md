# Reference parity contract

This document defines what “reproduced relative to the legacy applications”
means for this project. It is a test contract, not a Nikon protocol
specification and not authorization for live hardware work.

## Reference hierarchy

1. **Nikon Photo Secretary II for F100 — manufacturer reference.** It is the
   primary executable behavioral reference available to this project because
   Nikon supplied it for the F100.
2. **Camera Companion — independent third-party cross-check.** Agreement with
   Photo Secretary strengthens a conclusion; disagreement must be recorded and
   investigated rather than silently resolved in its favor.
3. **Existing third-party captures and private static analysis — supporting
   evidence.** These constrain byte framing and interpretation but do not
   replace a successful run on this project's hardware.
4. **The Mac client — implementation under test.** It must not be used as its
   own reference.

“Manufacturer reference” does not mean “published protocol specification.”
Photo Secretary can contain application-specific open lifecycles, timeouts,
retries, display conversions, and bugs. The comparison target is semantic
behavior for the same camera state, not byte-for-byte identity between two
applications whose transport lifecycles are already known to differ.

## Offline comparison contract

The `compare` command decodes an LQ payload through the same `decode_lq()` path
used by the client and compares it with the asserted subset in a reference JSON
file:

```sh
python3 f100_readonly.py compare \
  --reference fixtures/golden/simple_one_roll.reference.json \
  --capture fixtures/golden/simple_one_roll.hex
```

It reports every asserted JSON path as:

- `MATCH`: reference and decoded values are equal;
- `DIFFER`: values or list lengths differ, or an asserted field is missing;
- `UNKNOWN`: the reference explicitly contains `null` for that field.

Exit status is `0` for an overall `MATCH`, `3` for `DIFFER`, and `4` for
`UNKNOWN`. Invalid reference metadata or malformed payloads fail before a
comparison result is produced.

The comparison is intentionally a reference-subset comparison. Decoder notes,
local table paths, and new non-reference fields do not create false failures.
Raw byte-valued frame fields remain present even when optional tables also
produce display values.

## Reference JSON v1

```json
{
  "schema": "f100-parity-reference/v1",
  "source": {
    "application": "nikon_photo_secretary_ii",
    "reference_role": "manufacturer_reference",
    "evidence_kind": "application_export",
    "hardware_validated": false
  },
  "expected": {
    "mode": "simple",
    "roll_count": 1,
    "rolls": []
  }
}
```

Allowed source pairs are fixed so files cannot casually reverse the evidence
hierarchy:

| `application` | Required `reference_role` |
| --- | --- |
| `nikon_photo_secretary_ii` | `manufacturer_reference` |
| `camera_companion` | `independent_cross_check` |
| `synthetic` | `synthetic_golden` |

Allowed `evidence_kind` values are `synthetic`, `application_export`, and
`wire_capture_transcription`. Synthetic references must use `synthetic` and
cannot claim `hardware_validated: true`. Application and hardware metadata are
assertions made by the file author; the comparison tool checks consistency but
does not authenticate provenance.

### Hardware-validation provenance gate

An application reference with `hardware_validated: true` is rejected unless its
`source.provenance` object contains all of the following:

- a non-empty `run_id`;
- `captured_at_utc` as UTC ISO-8601;
- the exact `application_version` recorded for the run;
- the exact `approval_scope` and `camera_state`;
- `raw_capture_sha256` as 64 lowercase hexadecimal characters;
- a positive `raw_capture_size_bytes`.

This gate prevents a bare Boolean from promoting a file to hardware evidence.
It still does not authenticate those assertions; the immutable private evidence
ledger must support them. The unexecuted starting files are
[`REFERENCE_RUN_RECORD_TEMPLATE.md`](REFERENCE_RUN_RECORD_TEMPLATE.md) and
`fixtures/templates/nikon_photo_secretary_ii.reference.template.json`.

## Current golden fixtures

The distributed fixtures are newly authored synthetic sequences covering:

- simple mode with one roll and one frame, including shutter raw code `0xFD`;
- detailed mode with two roll boundaries and derived flag fields;
- an empty roll;
- a deliberately truncated negative input.

They establish deterministic parser behavior only. They contain no bytes
captured from a physical F100 and no export copied from Photo Secretary or
Camera Companion. A synthetic `MATCH` cannot establish application parity,
live compatibility, electrical safety, or Nikon conformance.

## Future live acceptance criteria

A Photo Secretary parity claim requires all of the following after separately
approved hardware work:

1. Exact camera state, film-data state, hardware path, application version, and
   run identifier are recorded.
2. Photo Secretary's complete relevant raw TX/RX and its displayed or exported
   result are preserved with timestamps, sizes, and SHA-256 values.
3. The same immutable response payload is replayed through the Mac decoder and
   all asserted roll, frame, raw-field, and display-field values match.
4. A separately approved Mac live read reproduces the same semantic result
   without a write, deletion, silent retry, malformed frame, or unexplained
   trailing data.
5. Camera Companion is run as an independent cross-check where useful; any
   disagreement is retained in the result rather than overwritten.

Until those conditions are met, the strongest allowed claim is “synthetic
offline parity checks pass.”
