# Synthetic LQ golden fixtures

These fixtures are project-authored synthetic byte sequences. They exercise the
observed LQ structures without containing bytes captured from a physical camera
or copied from Nikon Photo Secretary II or Camera Companion.

Each valid `.hex` payload has a paired `.reference.json` file using
`f100-parity-reference/v1`. The reference source is deliberately labeled
`synthetic_golden` and `hardware_validated: false`.

They can establish deterministic parser behavior only. A successful comparison
does not establish parity with Nikon Photo Secretary II, live F100 behavior,
electrical safety, or Nikon specifications.

