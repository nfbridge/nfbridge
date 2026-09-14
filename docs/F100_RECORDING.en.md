# F100 recording limits and settings conditions

Recording starts only after film is loaded. Factory defaults are recording off and deleting old data when memory is full. Read the camera to establish its current settings.

- Changing recording settings requires both empty record memory and frame counter E. The app cannot read film presence, so it asks the operator to inspect E immediately before NP. Erasing records does not establish E.
- Changes apply when the next film is loaded and advanced to the first frame. Settings read-back is not evidence that new shooting records have been captured.
- Stored ISO is from the last exposed frame. Earlier ISO settings changed mid-roll are lost. Last recorded ISO in tables and rating_ei in roll logs describe this value, not a verified ISO for every frame.
- This public app does not write ISO to scan images. A future scan workflow is designed to require confirmation that sensitivity did not change within the selected roll before including ISO. Exported CSV leaves ISO blank by default.
- Multiple-exposure data describes the first exposure only. The flag may remain after cancelling subsequent exposures; completed exposure count is unknown.
- With Stop shooting, switching power off and on after FUL can clear the warning and allow shooting without recording data. Preserve stored records and make memory space before expecting recording to resume.
- Overwriting old data for one new roll can remove multiple old rolls, potentially more than two.
- Importing mid-roll is supported. Roll logs default to status imported, which does not assert completion. A user who knows the roll is finished may change it to shot.

The tested USB setup uses PL2303 and the built-in macOS driver. It is an unofficial compatible configuration, different from the manual's MC-31/MC-33, PC serial port and powered-off connection procedure. It is not Nikon endorsement or electrical certification.

[한국어](F100_RECORDING.ko.md). Source: Nikon AC-2WE Photo Secretary II for F100 manual, printed pp.11 and 23–25. GUI import, settings changes and erasure were physically exercised on one developer-owned Mac/F100 setup; this does not establish broader compatibility.

[Simple/Detailed fields and 36-exposure equivalents](../README.en.md#how-do-simple-and-detailed-differ) · [Capacity calculation](CAPACITY.md) · [Archive checks before erasing](ARCHIVE_CHECKS.md)
