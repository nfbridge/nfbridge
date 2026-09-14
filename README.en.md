# Neo Film Bridge

**View the shooting information stored in your Nikon F100 on a Mac and save it as files.**

With recording enabled, the F100 saves shutter speed, aperture and other settings for each frame. This tool brings those records to your Mac as a table and saved files. It cannot recover information from photos taken before recording was enabled.

[한국어](README.md) · [Detailed guide](docs/GETTING_STARTED.md) · [Release notes](RELEASE_NOTES.en.md)

The source code is in this repository. Download the prebuilt Apple Silicon Mac app ZIP from [Releases](https://github.com/nfbridge/nfbridge/releases), then read `START_HERE.en.md` after unzipping it.

## What can I use now?

**v0.7 is still in development. It is not yet a finished app that lets you connect a camera and complete everything on your own.**

| Button | What it does | Available now? |
|---|---|---|
| Recording settings | Turns recording on or changes camera settings. | Connected to the GUI, with state checks and confirmation. Tested with the developer-owned Mac and F100. |
| Import | Brings stored camera records to your Mac. | Connected to the GUI; saves records to the library and export files. Tested with the developer-owned Mac and F100. |

GUI import, erasure and recording changes have been tested with the developer-owned Mac and F100. The v0.7.1 build also passed first-use connection and GUI import and save (one roll, 12 frames) on an additional Mac. The app build targets Apple Silicon. Its bundled binaries require macOS 14.0 or later, but physical testing covers only macOS 26.6.2 and 26.2; earlier macOS releases and Intel Macs remain unverified.


**This release does not write metadata to scan images.** The scan button and screen are excluded, and ExifTool is not bundled. The exported ExifTool CSV is a working file for later use; it does not modify photos automatically.

Hover over a button for a short explanation. **Open saved shooting records** opens a previously saved `shooting-data.json`. **Document template** controls the output language and Markdown journal layout. The built-in template is ready to use.

## Opening the app

**If you received an app ZIP**, unzip it and open `Neo Film Bridge.app`. You can move it to Applications if you like. A ZIP containing source files without an `.app` is for developers.

If your Mac blocks an app you obtained from a trusted source, go to **System Settings → Privacy & Security → Open Anyway** and follow the prompts. The app is not notarized by Apple, so a warning may appear. A Mac managed by your employer or school may not allow this exception. [Apple's instructions](https://support.apple.com/en-us/102445)

The **English / 한국어** button switches languages and remembers your choice next time. File selection windows follow your Mac's language setting.

## Which cable do I need?

You need an **F100-compatible 10-pin data cable**. A cable that only releases the shutter is not suitable.

The tested setup uses Prolific PL2303 and the built-in macOS driver. **This app does not supply a USB cable driver.** The tested setup needed no separate driver installation. If another cable needs one, you must check its manufacturer's macOS driver and supported versions and obtain it yourself. You can search for `Nikon F100 10-pin data cable PL2303`, but ask the seller to confirm **F100 shooting-data transfer** before buying. Using the same chip does not make every cable compatible. This setup also differs from the Nikon cable and PC serial port described in the original manual.

## Connecting and importing

Choose **Import** and enter a library name to use for this camera. On first use, follow the prompts to disconnect the cable and connect its USB end first for inspection. Later connections check the registered cable against the current connection. Close the Windows VM and other camera connection programs.

After import, the app shows the rolls and save location. Reimporting identical records does not duplicate library entries; additional frames from an unfinished roll are saved while earlier records are retained.

**Recording settings** reads the current settings first. Choosing a change leads to a separate confirmation. **Save and erase all camera records…** only erases records. To change settings afterwards, select them separately.

## What can I do with the records?

When you save, choose the files you need from the five options below. **HTML, the journal, and original data are enough to start.** Use HTML to view the records, or CSV to edit a table.

| File type | What is it for? |
|---|---|
| HTML | A shooting-information table you can view in a browser such as Safari. |
| Shooting journal (Markdown) | A roll-by-roll journal made of text and tables. Edit it in a text editor or a notes app such as Obsidian. |
| JSON (original data) | Keeps the original and interpreted values exactly as read by the app. It lets the app reopen the record later; you do not need to read or edit it yourself. |
| Regular CSV | A table you can open in a spreadsheet such as Numbers or Excel. |
| EXIF working CSV | A working table for applying information to scans, separate from the ordinary CSV. Match files to frames before using it; it is not ready to run as-is. |

At the start of Import, choose where to save and name a new folder. The library name is suggested by default; the camera's internal record number is not added. If the name exists, choose another to preserve those files. The app suggests the last successful location next time. Internal communication records are stored separately.

The export folder also contains one hidden bookkeeping file. Choosing the EXIF working CSV creates its row map and usage notes too. The app library is stored at `~/Library/Application Support/Neo Film Bridge/`.

Choose Korean or English output, or your own layout, under **Document template**. [Using your own template](docs/DOCUMENT_TEMPLATES.md)

## How do Simple and Detailed differ?

**Simple keeps basic shooting values so more records fit. Detailed keeps more information about how each shot was made.**

| Recorded information | Simple | Detailed |
|---|---|---|
| Frame number, shutter speed, aperture and shooting focal length | Yes | Yes |
| Flash use and multiple-exposure flag | Yes | Yes |
| Roll number and last recorded ISO for the roll | Yes | Yes |
| Lens zoom range and maximum aperture at each end | No | Yes |
| P/S/A/M exposure mode and metering method | No | Yes |
| Exposure compensation, flash compensation, manual meter deviation and rear-sync distinction | No | Yes |

Switching to Detailed later cannot recover fields omitted during Simple recording. **Choose Simple for basic shooting values, or Detailed to review more of your shooting settings.**

| Mode | Frame capacity | Equivalent in 36-exposure rolls | Basis |
|---|---|---|---|
| Simple | **About 2,830 frames expected** | **About 78.6 rolls** | Calculated from measured record sizes; not tested to full memory. |
| Detailed | **1,103 frames stored in a test** | **About 30.6 rolls** — 30 rolls plus 23 frames | One physical full-memory test. |

The Simple estimate assumes both modes use the same storage space and records are grouped into 36-exposure rolls. Actual capacity may vary with roll length and camera memory management. The Detailed figure is a conversion of the observed frame count, not another test using 36-exposure rolls. [Calculation](docs/CAPACITY.md)

## Things to know before using it

**Changing settings:** The camera's record memory must be empty, and the film counter must show **E**. The app cannot read that counter, so it asks you to check it yourself. It then reads the camera state again and changes settings only if the state is unchanged. New settings apply **when the next film is loaded and advanced to its first frame**.

**ISO:** The camera stores only the last exposed frame’s ISO. Earlier ISO values are unavailable if you changed sensitivity during the roll. The table labels this as Last recorded ISO.

**Multiple exposures:** Only the settings for the first exposure are stored. The total exposure time and the number of completed exposures are unknown. Other unavailable values, such as actual Bulb duration, are not filled in by guesswork either.

**Deleting records and full memory:** Importing does not erase camera records. Deletion requires saving the records to your Mac and confirmation. However, if you choose automatic overwrite on the camera, one new roll can remove several older rolls. After `FUL` stops shooting, switching the camera off and on can let you **keep shooting without recording data**.


## Save shooting records to your Mac before erasing them

The saved files contain shooting information such as shutter speed and aperture. **You can keep viewing them on your Mac after erasing the camera records, but you cannot put them back into the camera.** They do not contain photographs or restore the camera as a whole.

Changing recording settings controls what the camera records during future shooting. It does not edit existing frame records or upload them to the camera.

Before erasing, the app makes a new archive and rereads it, checking each roll against the current camera records. The confirmation shows the actual checked count and folder, for example **“Verified on your Mac: 5/5 rolls · 117 frames”** (illustrative numbers). **Unsaved shooting records cannot be recovered after erasing.** Unverified rolls are listed and erasing stops. The archive is checked again immediately before sending the erase command, so a file changed or removed during confirmation also stops the operation.


[How saved records and file checks are verified](docs/ARCHIVE_CHECKS.md)

## If something goes wrong

- **Cannot connect to the camera:** Check power and cable connections, close the Windows VM and other camera programs, then try Import again. If the Mac does not recognize the cable itself, check with its manufacturer whether a macOS driver is required. The app does not include one.
- **Cable inspection does not match:** Restore the previous USB connections, or use **Help → Check cable again**.
- **Import shows zero rolls:** This means the camera record memory is empty, unlike a communication failure. Check the message about whether recording is enabled. Values from before recording was enabled cannot be recovered.
- **Cannot change recording settings:** Both counter E and empty record memory are required. Erasing records does not change the counter to E.
- **Erasing stopped because saved records could not be verified:** Check the shooting-record file in the displayed folder and save again. Camera records are not erased while that check fails.
- **Another error appears:** Follow the message. Logs to share with a developer are in `~/Library/Logs/Neo Film Bridge/`.

## Projects and communities that helped

Thanks to pySerial, Python/Tk, PyInstaller, tkinterdnd2 and ExifTool, and to the earlier work in nikonserial, pikon and the F90X documentation. [Project descriptions and links](docs/GETTING_STARTED.md#thanks-and-project-status)

The [r/AnalogCommunity post](https://www.reddit.com/r/AnalogCommunity/comments/15m5kxj/nikon_ac2we_photo_secretary_ii_for_windows_works/) sharing Photo Secretary preservation and Windows usage experience also helped us find early research material.

This is an independent project, unaffiliated with Nikon. Nikon and other names and trademarks belong to their owners. Private shooting records and original personal templates are not distributed. Neo Film Bridge's own code is licensed under [GPLv3](LICENSE); bundled components retain their separate licenses in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
