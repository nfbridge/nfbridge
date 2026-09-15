# v0.7.2 preview package checklist

- [x] Current Apple Silicon `.app` built and ad-hoc signed.
- [x] The release ZIP is built with `scripts/package_macos_app_zip.sh` and contains the app, both start guides, GPLv3 LICENSE, third-party notices and component license texts.
- [x] Offline regression suite and synthetic comparisons passed on the build machine.
- [x] Project Mac/F100 GUI import, recording-setting changes and camera-record erasure physically exercised with user confirmations.
- [x] Scan-image writing is excluded; ExifTool is not bundled.
- [x] Private captures, personal roll logs and proprietary binaries are excluded from the source package.
- [ ] Fresh macOS user account installation and first-run walkthrough.
- [ ] Broader cable, Intel Mac and macOS 14.0–26.5 compatibility tests.
- [x] GPLv3-only license selected for Neo Film Bridge's own code; bundled licenses remain separate.
- [x] Separate private research repository retained.
- [x] Owner approved a new public `nfbridge` source repository with fresh history.
- [x] Owner approved public distribution of the prebuilt app after the source push.

Run `./verify.sh` after any source or documentation change, regenerate `MANIFEST.sha256`, then unpack and verify the final ZIPs, app signature and isolated demo launch. Never upload a ZIP whose only top-level item is the `.app`.
