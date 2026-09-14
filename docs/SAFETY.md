# Safety boundary

The original implementation completed one physical Mac/F100 read using a
Prolific 067B:2303 adapter and AppleUSBPLCOM. See [validation](VALIDATION.md)
for the measured results and limits. The guided workflow in this development
preview passed offline tests and was used for camera import, erase and
recording-setting changes on the developer-owned Mac and F100. See the private
project worklog sections 232–234 for the tested sequence. Other cameras,
cables and a fresh-user installation are unverified.

Start with [the guided instructions](../START_HERE.md). The launcher handles
session preparation and asks before reading the connected camera. It does not
require Windows. The older cable-only research assistant is not the user entry
point. Offline examples and table checks never open a serial port.

The normal read path reads existing camera records. The separately selected
[maintenance operation](MAINTENANCE.md) can archive, erase and enable Detailed
recording with separate confirmations. The GUI path was physically exercised on
the developer-owned Mac/F100 with user confirmations, including the counter-E check. A successful
empty result and a failed connection are different outcomes. Keep the original
capture files when investigating either.

The read-only client implements payload-free `CQ`, `MQ`, `OQ`, and `LQ` only. `NP`, `DP`,
`EP`, unknown opcodes, and all command payloads are rejected. Live LQ has an
additional explicit experimental gate and remains disabled by default.

The cable identity command is observational. It keeps the camera disconnected,
does not open a serial port, and cannot establish electrical safety, firmware
authenticity, BadUSB absence, or camera compatibility. Its evidence is sealed
as identity-only and cannot be promoted into an admission approval.

Admission, orchestration, and capture hashes protect evidence continuity; they
do not prove voltage, polarity, wire timing, or physical camera receipt.


The separately bound maintenance client permits only EP then a one-byte NP
setting derived from freshly read MQ. DP remains prohibited. It does not
change the read-only encoder or give read-only plans write authority.

The GUI uses separately bound `record-settings` (one NP byte from 01/02/03/09/0A/0B) and `erase-records` (one empty EP) operations. Both preserve existing verification and confirmation checks. Camera archives are for viewing on the Mac, not restoration to the camera. This path was exercised on one real Mac/F100 configuration; simulated tests alone do not establish broader hardware compatibility.
