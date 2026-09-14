# References and acknowledgements

## Runtime dependency

[pySerial](https://github.com/pyserial/pyserial) supplies serial-port access for live reads. The project pins version 3.5. It retains its own BSD-3-Clause license and is not relicensed by nfbridge's GPLv3 license.

## Direct research input

[schoerg/nikonserial](https://github.com/schoerg/nikonserial), revision `24ceb6ed4743c376deb26a42c345609e18547323`, supplied communication captures and connection documentation examined during initial protocol analysis. Its captures, screenshots and pinout images are not redistributed here. Attribution is not a claim of ownership or permission to redistribute that material.

## Related research

- [rhaamo/pikon](https://github.com/rhaamo/pikon): earlier N90/N90s (F90/F90X) data-link implementation, consulted for comparison and historical context.
- [antarktikali/f90x-serial-documentation](https://github.com/antarktikali/f90x-serial-documentation): documentation of F90X/N90s serial communication, consulted for context rather than as evidence that the same commands apply to F100.
- [Ken Hancock's N90 Buddy protocol documentation, archived](https://web.archive.org/web/19981207005100/http://members.aol.com/khancock/pilot/nbuddy/protocol.html): historical F90-family background referenced by the earlier research.
- [enthdegree/f100](https://github.com/enthdegree/f100): repair research consulted as background. Its memory-access leads were not implemented as F100 commands in this client.

## Reference applications

Nikon Photo Secretary II for F100 served as the manufacturer reference. [Camera Companion](https://www.holymoose.com/ccbuy.html) supplied an independent application comparison. Their displayed records and observed communication were compared against records read from the same camera. Neither application, its extracted resources nor its private capture files is bundled.

These acknowledgements distinguish dependencies, direct analysis inputs and contextual references. They do not imply endorsement, shared authorship, transferred licensing rights or compatibility with every camera discussed in the linked projects.

## Community research leads

The [r/AnalogCommunity post about preserving and running Photo Secretary II on Windows](https://www.reddit.com/r/AnalogCommunity/comments/15m5kxj/nikon_ac2we_photo_secretary_ii_for_windows_works/) helped locate historical reference material during initial research. It is a community report, not evidence of nfbridge compatibility or endorsement. The original software is not bundled.
