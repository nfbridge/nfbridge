# Publication scope

This public repository starts with fresh history from a reviewed, allowlisted source
export. It does not inherit the private development repository's Git history.
The separate macOS app archive bundles its runtime and
listed third-party libraries; see [third-party notices](../THIRD_PARTY_NOTICES.md) and the accompanying
license texts. It does not bundle ExifTool.

## Included

- Project-authored Python source and offline tests.
- Small project-authored synthetic JSON and hex fixtures.
- Public-safe documentation and an integrity manifest.
- A requirements file naming and hashing an optional external dependency.

## Excluded

- Third-party executables, installers, libraries, drivers, firmware, manuals,
  sample resources, or archives in the source export. The macOS app's declared
  runtime libraries are the exception described above.
- Packet captures, process-monitor traces, VM images, screenshots, and raw
  serial sessions derived from third-party software or hardware.
- Disassembly, bulk strings, exact extracted value tables, and fixtures capable
  of reconstructing proprietary resources.
- Credentials, registration data, device serial numbers, personal identifiers,
  local absolute paths, cloud IDs, and private links.
- Internal audit reports, handoffs, transcripts, worklogs, and unpublished
  research evidence.
- The private v0.5 fixed-reference adapter command, its device identity, and its
  physical observation evidence.
- The former Windows/UTM first-use assistant, preauthorization inspection, and
  serial relay tools, plus tests devoted only to those research workflows. The
  public-source exporter omits these files and their CLI entry points; its
  orchestrator accepts only the macOS client plan mode.

The earlier private GitHub repository contains research-era commits and remains
private. This public repository contains the active USB admission, reconnect and
live-operation binding checks.

The macOS app build excludes the three research-only Python modules named above.
The public-source export was verified separately before publication.

Names and high-level factual descriptions of outside references may appear for
provenance and interoperability context. They are not bundled or relicensed.
