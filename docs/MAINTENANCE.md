# Archive records, erase and set up Detailed mode — development implementation

The saved record archive is for viewing and processing on the Mac, not for restoring records to the camera. NP changes recording settings; it does not upload shooting records. Internal filenames retain `backup` for compatibility. Scan `_original` files are separate copies of photographs.

The optional maintenance entry point is separate from the read-only client.
Menu 3 in `Neo Film Bridge.command` prepares a dedicated device/session binding.
The earlier R2 path was tested on one camera. This revised E-confirmation candidate has not been tested on hardware. Do not treat the
previous read-only release's audit as approval of this new implementation.

The operation reads MQ/OQ/LQ, writes and rereads a local backup, and asks before
erasing. It rereads the entire camera record set to reject changes made during
review. EP is sent once. It requires OQ=0 and a one-byte LQ before offering
Detailed setup. After EP, it reads current MQ and sets only recording-ON and
Detailed bits (`current | 0x0A`), preserving the full-memory policy. If any bits outside observed mask 0x0B
are set in the post-erase MQ, stop without NP rather than copy unknown bits
into a write. Only NP payload 0x0A or 0x0B can reach the transport. It skips NP when those bits are already set. After a
separate settings confirmation and explicit operator observation of frame counter E, it rechecks OQ=0, one-byte LQ and zero frames, sends NP once and verifies MQ plus
empty LQ. With no roll container (OQ=0, LQ length1), global 00/01 is recorded
as observed and is not used to infer mode; final mode is verified by MQ.
For nonempty LQ, the mode consistency check remains in force. Cancellation after deletion leaves the camera erased and
settings unchanged; the backup remains.

A timeout, short write, disconnect, 79, unexpected ACK or read-back mismatch
stops the operation. There are no write retries and no automatic rollback.
An uncertain write may already have taken effect: review the retained capture
and perform a separate read before deciding what to do. Read-only requests
retain their existing one-empty-79 retry policy.

Backups are `backup-lq.bin` and `backup.json` inside the new capture directory.
Successful final verification creates `result.json`; failures retain the raw
capture and error manifest. The backup stores camera metadata, not photographs.
Self-hashes provide consistency checking, not authentication against a malicious
local process. Keep physical ownership of the camera during the operation.

The maintenance plan is explicitly scoped to `erase-and-detailed`, with DP and
automatic write retry disabled. Existing read-only plans cannot authorize it.
The existing orchestrator's read-only capture assessment deliberately rejects
maintenance captures as requiring separate operation review; it never reports
a read-only PASS for writes.

Developer entry: `f100_maintenance.py --help`. The plan generator accepts
`--mac-command maintenance`; its preview includes all required binding paths
and the explicit `--execute-erase-and-detailed` flag. This flag does not skip
any interactive confirmation, including the independent E question. Neither the demo nor normal read menu sends
NP or EP. The read-only encoder continues to reject NP/DP/EP.

Changing modes while retaining records is outside this implementation. Existing
Simple records cannot acquire Detailed fields retroactively. Mixed-mode record
handling has not been observed.

The deletion prompt displays the verified backup SHA-256. For the first
physical trial, report that actual new backup hash in chat before confirming
deletion; this implementation revision has not performed a physical write.

The app cannot measure the film counter. A declined or interrupted E confirmation prevents NP, but an already completed EP is not undone. E confirmation records actor and channel. For chat-relayed input use --confirmation-actor assistant --confirmation-channel chat-relay; otherwise the defaults describe a user answering directly in the terminal. Settings apply to the next film advanced to its first frame.
