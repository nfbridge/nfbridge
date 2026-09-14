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
