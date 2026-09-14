# 보관 확인 / Archive checks

## 한국어

카메라 기록을 전부 지우기 전에 **이번 카메라 읽기의 촬영기록을 새 폴더에 보관**합니다. 앱은 그 폴더의 `shooting-data.json`을 다시 읽어 원본 데이터와 확인 값, 모드, 각 롤의 전체 내용을 비교합니다. 롤 번호가 같다는 이유만으로 저장됐다고 판정하지 않습니다. 오래된 일부 기록이나 같은 번호의 다른 기록은 현재 롤의 보관을 대신할 수 없습니다.

삭제 확인창에는 실제 확인한 롤 수·컷 수·보관 폴더가 나옵니다. 하나라도 확인하지 못하면 그 수와 롤 번호를 표시하고 삭제를 중단합니다. 보관 확인 없이 강제로 삭제하는 버튼은 없습니다. 사용자가 확인창에서 동의한 뒤에도 삭제 명령 직전에 파일을 다시 검사합니다. JSON을 보관하면 앱에서 다시 열 수 있지만, 카메라로 돌려 넣을 수는 없습니다.

이 검사는 **이번에 새로 만든 보관 폴더**를 대상으로 합니다. 사용자가 옮겨 둔 모든 과거 폴더나 다른 디스크까지 검색했다는 뜻은 아닙니다. 읽을 수 없는 파일은 ‘확인하지 못함’이며 반드시 어디에도 사본이 없다는 뜻은 아닙니다. 같은 내용의 롤도 서로 다른 필름일 수 있으므로 필름 자체의 신원은 보증하지 않습니다.

SHA-256 또는 해시값은 파일 내용이 달라졌는지 비교할 때 쓰는 긴 확인 값입니다. 사용자가 직접 계산하거나 외울 필요는 없습니다. 문제를 문의할 때 파일과 함께 전달하면 개발자가 같은 파일인지 확인하는 데 도움이 됩니다. 값이 같아도 카메라가 기록한 촬영값 자체의 정확성이나 사용자의 신원을 증명하지는 않습니다.

스캔 사진 옆의 `scan01.jpg_original`은 위 촬영기록 파일과 별개입니다. 스캔에 정보를 쓰기 전의 사진을 보관한 파일입니다. 이미 그 파일이 있다면 덮어쓰지 않고 작업을 멈춥니다. 기존 폴더는 그대로 보관하고, 다시 작업할 JPEG/TIFF만 새 폴더에 복사해 선택할 수 있습니다. 자동 원상 복구 기능은 아직 없습니다.

## English

Before erasing all camera records, the app saves **the current camera read to a new archive folder**. It rereads `shooting-data.json` and compares the original payload, its digest, the recording mode and the entire content of each roll. Matching roll numbers alone do not establish that the current records were saved. An older partial roll or different records with the same number do not substitute for the current roll.

The confirmation displays the verified roll/frame count and archive folder. Any unverified rolls are counted and listed, and erasing stops. There is no force-erase override. The file is checked again immediately before the erase command, after the user's confirmation. The JSON can be reopened in the app, but cannot be restored to the camera.

This checks **the newly created archive folder**, not every historical folder or external drive. An unreadable file is unverified; it does not prove no other copy exists. Matching records do not establish physical film identity.

SHA-256, or a hash, is a long value for comparing file contents. You do not need to calculate or memorize it. Sharing it with a file helps a developer check that they have the same file. A match does not establish correct camera values or authenticate a user.

A scan's `scan01.jpg_original` is separate from the shooting-record archive: it preserves the photograph before metadata editing. The app stops rather than overwriting an existing copy. Keep the old folder intact, and copy only the JPEG/TIFF images to be edited again to a new folder. Automatic restoration is not implemented.
