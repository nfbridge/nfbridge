# Neo Film Bridge v0.7.1 preview — macOS app candidate

Fixed first-use cable inspection rejecting distinct disks with the same display name. If a system check fails, the app now identifies the failed check instead of assuming a USB permission problem. On an additional Mac, the patched build imported and saved one roll with 12 frames through the GUI; the generated HTML table was opened and checked.

[한국어](RELEASE_NOTES.md)

This preview packages the current Apple Silicon macOS app with Korean and English guidance. It reads existing Nikon F100 shooting records, displays them by roll and frame, and lets the user save selected HTML, Markdown, JSON, ordinary CSV and EXIF-working CSV outputs. The EXIF-working CSV is a preparation file; the app does not write to scan images and ExifTool is not bundled.

The app also includes recording settings and complete camera-record erasure. These are separate, confirmed camera-write operations. Setting changes require the user to check that the camera counter shows E and that recorded memory is empty. Erasure first saves and checks the current records on the Mac, then requires a final confirmation. A Mac archive is for viewing and cannot be restored into camera memory.

GUI import, erasure and recording-setting changes were physically exercised with the developer-owned Mac and F100 using a Prolific cable, with user confirmations and retained captures. The patched build also passed first-use connection and GUI import and save on an additional Mac. This does not establish compatibility with other cameras or cables. The Apple Silicon app declares macOS 14.0 as its binary minimum; physical testing covers the developer Mac on macOS 26.6.2 and the additional Mac on macOS 26.2. A fresh-user download and installation flow has not been validated. The app is ad-hoc signed, not Apple-notarized.

The source archive contains synthetic regression fixtures but no private camera captures, personal roll logs, proprietary application binaries, extracted tables or vendor drivers. Neither archive supplies a USB cable driver; the tested cable used macOS's built-in driver. Users of other cables must obtain any required compatible driver from the cable manufacturer. Neo Film Bridge's own code is GPLv3-only; bundled components retain their separate licenses. The public app ZIP is available from this repository's Releases.
