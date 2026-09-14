# Nikon Photo Secretary II reference-run record template

Status: **UNEXECUTED TEMPLATE — NOT HARDWARE EVIDENCE**

Copy this file for a future, separately approved hardware run. Do not edit this
template in place and do not mark any phase complete from memory. Store raw
artifacts immutably and keep derived JSON or reports separate.

## 1. Authorization boundary

- Run ID: `UNASSIGNED`
- Operator:
- Date and local time:
- Exact written approval text or durable reference:
- Approved phase and actions:
- Explicitly not approved:

Unchecked actions are not authorized:

- [ ] Passive cable inspection
- [ ] Powered cable inspection with F100 disconnected
- [ ] Physical F100 connection
- [ ] Photo Secretary Connect
- [ ] Photo Secretary CQ/MQ/OQ observation
- [ ] Photo Secretary Download/LQ observation
- [ ] Camera Companion cross-check in a separate run

No write, settings change, Delete/Erase, Reset, Time set, Rewind, NP, DP, EP,
EEPROM access, corrective retry, or unknown opcode belongs in this template.

## 2. Manufacturer-reference identity

- Application: Nikon Photo Secretary II for F100
- Role: manufacturer reference application, not a published protocol
  specification
- Exact displayed/file version:
- Executable filename:
- Executable byte size:
- Executable SHA-256:
- Installation/source identifier kept in private evidence:

Camera Companion must have a separate run record and remains an independent
third-party cross-check.

## 3. Hardware and state

- F100 pseudonymous identifier (do not publish a serial number):
- Camera power state before connection:
- Meter/standby state:
- Film and shooting-data state:
- Cable/adapter model and markings:
- USB VID/PID and device descriptors:
- Driver version and assigned port:
- Verified camera-side idle voltage, polarity, ground, TX/RX, and isolation:
- Capture equipment and topology:

## 4. Procedure and event log

Record every action and observation in order. Do not fill future steps in
advance.

| UTC timestamp | Actor | Action | Expected | Observed | Continue/stop basis |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

## 5. Raw evidence ledger

| Artifact | Original/derived | Byte size | SHA-256 | Capture scope | Immutable location |
| --- | --- | ---: | --- | --- | --- |
|  |  |  |  |  |  |

Required raw evidence includes complete timestamped TX/RX, port open/close and
line settings, relevant USB activity, UI result, and the precise stop reason.
Record missing evidence as missing; do not reconstruct it silently.

## 6. Semantic parity record

- Source raw LQ artifact:
- Raw LQ byte range and extraction method:
- Reference JSON path:
- `f100-parity-reference/v1` source metadata reviewed by:
- `compare` command:
- Exit status:
- `MATCH` count:
- `DIFFER` count and paths:
- `UNKNOWN` count and paths:
- Display/export comparison:
- Unexplained discrepancy:

Set `hardware_validated: true` only after the reference JSON contains the exact
run ID, UTC capture time, application version, approval scope, camera state,
and raw-capture byte size and SHA-256 required by the comparator. Passing that
schema gate authenticates nothing by itself; the private immutable evidence
must still support every value.

## 7. Stop and claim discipline

- Stop condition reached:
- Commands not attempted:
- Camera/film/data condition after the run:
- Follow-up requiring new approval:

This record alone does not justify `live-safe`, `Nikon-compatible`,
`Nikon-specification compliant`, or general hardware-validation claims.

