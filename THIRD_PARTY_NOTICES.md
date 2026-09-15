# Third-party components in the macOS app

Neo Film Bridge's own code is covered by the repository LICENSE. The app also bundles the following independently licensed components. The license texts listed below are included beside the app in its distribution ZIP and in the source archive under `third-party-licenses/`:

- Python 3.12 runtime — Python Software Foundation License. License text: `third-party-licenses/Python-LICENSE.txt`.
- pySerial 3.5 — BSD-3-Clause, copyright 2001–2020 Chris Liechti. License text: `third-party-licenses/pySerial-LICENSE.txt`; official version: https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt
- tkinterdnd2 0.6.3 — MIT, copyright 2020 Philippe Gagné. License text: `third-party-licenses/tkinterdnd2-LICENSE` and within the bundled app metadata.
- PyInstaller 6.22.3 bootloader — GPL-2.0-or-later with the PyInstaller exception. License text: `third-party-licenses/PyInstaller-COPYING.txt`.
- Tcl/Tk runtime — Tcl/Tk license terms. License texts: `third-party-licenses/Tcl-license.terms` and `third-party-licenses/Tk-license.terms`; projects: https://github.com/tcltk/tcl and https://github.com/tcltk/tk

ExifTool and its executable are **not** bundled. Its working CSV output is a preparation file, not an image metadata write.
