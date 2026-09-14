# Shooting-data exports

The save dialog offers an HTML table, UTF-8 BOM shooting-data CSV, JSON
with decoded values and `_source.payload_hex` / SHA-256 when produced by the
live or demo reader, an unmapped ExifTool CSV, and one Markdown roll log per roll.
Only selected user-facing formats are created. Each output directory also has
a hidden `.nfbridge-export-status.json` recording what was generated.
The ordinary CSV also retains the complete per-frame decoded/raw object in a
JSON column. Offline callers supplying decoded JSON without a payload cannot
reconstruct it: no raw source is invented for those calls.

Live import asks once per roll for optional order / film code / date / film name.
Enter skips this. `--metadata <json>` supplies equivalent entries keyed by camera
roll number. `roll_id` can override the generated filename; the default is
F100_roll<number>. `--roll-sections` adds per-frame headings. `--vault <folder>`
saves the selected destination for later imports under the output directory's
export-settings.json. It copies only generated Markdown, never replaces an
existing note, and records skipped copies in `.nfbridge-export-status.json`. This is not yet
library-aware note merging or deduplication. Demo mode never copies to a vault.

Markdown follows the approved roll-log example with editable subject, intent
and review fields left blank. Import date is tagged imported and explicitly
marked f100_date_source=imported unless the user supplies a date. Download time
is not a shooting date. Lens descriptions are recorded focal/aperture ranges,
not inferred branded model names. Simple has flash/multiple-exposure fields;
only unavailable Detailed columns receive dashes. Private historical roll logs
are not included in this package.

ExifTool CSV is a mapping template, not ready to execute: SourceFile is blank.
exiftool-row-map.json maps CSV row numbers to camera roll/frame IDs. The tool
does not run ExifTool, write image metadata or generate XMP sidecars. Bulb duration,
unknown values and unsupported TTL-to-EXIF-Flash mappings are left blank.
DateTimeOriginal is filled only with an explicit user datetime_original value
(YYYY-MM-DD HH:MM:SS); a date alone never becomes an invented midnight timestamp.
Numeric enum columns use ExifTool's `#` convention. Flash compensation uses
XMP-aux:FlashCompensation. ExifTool is not bundled.

References: [CSV documentation](https://exiftool.org/exiftool_pod2.html),
[XMP aux tags](https://exiftool.org/TagNames/XMP.html#aux).

Current verification covers file generation, escaping, mappings and no-overwrite
behavior. ExifTool execution against scan files and a complete fresh-user Mac
installation remain outside this output implementation's verified scope.
