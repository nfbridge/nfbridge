# Using Neo Film Bridge

[Back to the README](../README.en.md) · [한국어](GETTING_STARTED.ko.md)

The app brings shooting records **already stored by a Nikon F100** to your Mac. Enable recording on the camera for future frames. Settings that were never recorded cannot be recovered.

## Getting started

1. Get an **F100 shooting-data cable** for its round 10-pin connector. The physical test used one Prolific PL2303 `067B:2303` setup recognized by the built-in macOS driver. The app does not include a USB cable driver. If another cable needs a separate driver, check the manufacturer's macOS support and obtain that driver yourself. A shutter-release cable or another cable with the same chip is not established as compatible.
2. Unzip the app package and open `Neo Film Bridge.app`. This Apple Silicon build requires macOS 14.0 or later; physical tests cover macOS 26.6.2 and 26.2. The app is not Apple-notarized. If a Mac blocks a copy you trust, use **System Settings → Privacy & Security → Open Anyway**. [Apple's instructions](https://support.apple.com/en-us/102445)
3. Click **Import**. Follow the first-use cable check in the app. Quit Windows VMs and other camera-connection programs. Review the rolls and frames, then choose a save location and the output formats you want.

An empty camera can return 0 rolls; that differs from a connection failure. To reopen saved records, use **Open saved shooting records** and select `shooting-data.json`.

## Recording settings and erasure

**Recording settings** reads the current state and lets you choose what future frames record and what happens when memory fills. A change requires empty recorded memory and the camera's film counter at **E**. The app cannot read the E display; you must check it yourself. It rereads the camera after your confirmation. The new setting applies when the next film is loaded and advanced for shooting.

**Erase all camera shooting records…** is a separate operation. The app first saves the records on your Mac and rechecks each roll's contents, then asks again before erasure. You can view the Mac copy but **cannot restore it to camera memory**. Importing alone does not erase camera records.

## Files you can save

Choose any of HTML (viewing), Markdown roll logs (notes), JSON (original values and reopening), ordinary CSV (spreadsheet editing), and EXIF-working CSV. The EXIF-working CSV only prepares a future scan workflow. **This app does not write to scan images and does not bundle ExifTool.** Document template settings choose output language and roll-log layout.

Unknown camera values remain unknown. Simple records basic values such as shutter, aperture and focal length; Detailed adds mode, metering and compensation. [Recording behavior](F100_RECORDING.en.md) · [Capacity](CAPACITY.md)

## If something goes wrong

For a connection failure, check power, cable and whether another program owns the port. For 0 rolls, check whether camera memory is empty and recording is enabled. If a setting change is refused, check both counter E and empty memory. If erasure stops, review the Mac save folder and any rolls the app could not confirm. [Archive checks](ARCHIVE_CHECKS.md)

## Thanks and project status

This is an independent project, unaffiliated with Nikon. The app uses [Python](https://www.python.org/), [Tcl/Tk](https://www.tcl.tk/), [pySerial](https://github.com/pyserial/pyserial), [PyInstaller](https://pyinstaller.org/) and [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2). [ExifTool](https://exiftool.org/) informed a future scan workflow but is not bundled. Earlier research benefited from [nikonserial](https://github.com/schoerg/nikonserial), [pikon](https://github.com/rhaamo/pikon), [F90X serial documentation](https://github.com/antarktikali/f90x-serial-documentation) and an [r/AnalogCommunity Photo Secretary post](https://www.reddit.com/r/AnalogCommunity/comments/15m5kxj/nikon_ac2we_photo_secretary_ii_for_windows_works/). Photo Secretary and Camera Companion were comparison references, not bundled programs. [More provenance](ACKNOWLEDGEMENTS.md)

GUI import, recording changes and erasure were physically exercised on the developer-owned Mac/F100 setup. First-use connection and GUI import and save (one roll, 12 frames) also passed on an additional Mac. Other cables and a fresh account's first launch remain untested. [Validation scope](VALIDATION.md)
