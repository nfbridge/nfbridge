# Neo Film Bridge 사용법

[처음으로 돌아가기](../README.md) · [English](GETTING_STARTED.md)

Nikon F100이 **이미 저장한 촬영정보**를 Mac으로 가져오는 앱입니다. 앞으로의 촬영정보를 남기려면 카메라의 기록 설정을 켜야 합니다. 이전에 기록하지 않은 컷의 설정은 되살릴 수 없습니다.

## 시작하기

1. F100의 원형 10핀 단자에 맞는 **촬영정보 전송용 데이터 케이블**을 준비합니다. 실물 시험은 Prolific PL2303 `067B:2303` 구성 한 가지로 했으며 macOS 내장 드라이버로 인식됐습니다. 앱에는 USB 케이블 드라이버가 없습니다. 다른 케이블에 별도 드라이버가 필요하다면 제조사의 macOS 지원 여부를 확인하고 직접 준비하세요. 릴리즈 케이블이나 같은 칩을 쓴 다른 케이블의 호환성은 확인되지 않았습니다.
2. 앱 ZIP을 풀고 `Neo Film Bridge.app`을 엽니다. Apple Silicon용 빌드이며 macOS 14.0 이상을 요구합니다. 실물 시험은 macOS 26.6.2와 26.2에서 했습니다. Apple 공증을 받지 않아 차단되면, 신뢰하는 파일인지 확인한 뒤 **시스템 설정 → 개인정보 보호 및 보안 → 그래도 열기**를 사용하세요. [Apple 안내](https://support.apple.com/en-us/102445)
3. **가져오기**를 누릅니다. 첫 연결에서는 앱의 케이블 확인 안내를 따르세요. Windows VM이나 다른 카메라 연결 프로그램은 종료합니다. 카메라에서 읽은 롤과 컷을 확인한 뒤 저장 위치와 필요한 출력 형식을 고릅니다.

처음부터 빈 카메라라면 0롤이 나올 수 있습니다. 이는 연결 실패와 다릅니다. 저장된 기록을 다시 열려면 앱의 **저장한 촬영기록 열기**에서 `shooting-data.json`을 고르세요.

## 기록 설정과 삭제

**기록 설정**에서 현재 상태를 읽고, 앞으로 기록할 모드와 메모리가 찼을 때의 동작을 선택합니다. 설정 변경은 카메라 메모리가 비어 있고 필름 카운터가 **E**일 때만 진행합니다. 앱은 E 표시를 읽지 못하므로 사용자가 직접 확인해야 합니다. 확인 후에도 앱이 카메라 상태를 다시 검사합니다. 새 설정은 다음 필름을 넣어 촬영할 때 적용됩니다.

**카메라 촬영기록 삭제…**는 별도의 작업입니다. 먼저 현재 기록을 Mac에 저장하고 롤별 내용까지 재확인하며, 마지막에 삭제 여부를 다시 묻습니다. Mac에 보관한 기록은 볼 수 있지만 **카메라로 복원할 수는 없습니다.** 가져오기만으로 카메라 기록이 지워지지 않습니다.

## 저장 파일

저장할 때 HTML(보기), 촬영일지 Markdown(메모), JSON(원본 값 보관·다시 열기), 일반 CSV(표 편집), EXIF 작업용 CSV 중 필요한 것만 선택합니다. EXIF 작업용 CSV는 스캔 파일과 컷을 맞추기 위한 준비 파일입니다. **이번 앱은 스캔 사진에 정보를 쓰지 않으며 ExifTool도 동봉하지 않습니다.** 문서 양식에서는 출력 언어와 촬영일지 모양을 고를 수 있습니다.

카메라가 알 수 없는 값은 임의로 채우지 않습니다. Simple 모드는 셔터·조리개·초점거리 같은 기본값을 남기고, Detailed는 촬영 모드·측광·보정 등 더 많은 값을 남깁니다. [기록 설정과 범위](F100_RECORDING.ko.md) · [용량](CAPACITY.md)

## 잘 안 될 때

연결 실패라면 전원·케이블·다른 프로그램의 포트 점유를 확인하세요. 0롤이면 카메라 메모리에 기록이 없는 상태인지, 기록 기능이 켜져 있는지 보세요. 설정이 거부되면 카운터 E와 빈 기록 메모리를 모두 확인하세요. 삭제가 멈췄다면 안내된 Mac 저장 폴더와 확인되지 않은 롤을 살펴보세요. [보관 확인 설명](ARCHIVE_CHECKS.md)

## 감사와 프로젝트 상태

이 프로젝트는 Nikon과 관계없는 독립 작업입니다. [Python](https://www.python.org/), [Tcl/Tk](https://www.tcl.tk/), [pySerial](https://github.com/pyserial/pyserial), [PyInstaller](https://pyinstaller.org/), [tkinterdnd2](https://github.com/Eliav2/tkinterdnd2)를 앱에 사용했습니다. [ExifTool](https://exiftool.org/)은 향후 스캔 작업을 위해 참고했지만 이번 앱에 넣지 않았습니다. 초기 연구에는 [nikonserial](https://github.com/schoerg/nikonserial), [pikon](https://github.com/rhaamo/pikon), [F90X serial documentation](https://github.com/antarktikali/f90x-serial-documentation)와 [r/AnalogCommunity의 Photo Secretary 글](https://www.reddit.com/r/AnalogCommunity/comments/15m5kxj/nikon_ac2we_photo_secretary_ii_for_windows_works/)이 도움이 됐습니다. Photo Secretary와 Camera Companion은 비교용 참조 프로그램이며 동봉하지 않았습니다. [자세한 출처](ACKNOWLEDGEMENTS.md)

실물 GUI 가져오기·설정 변경·삭제는 개발자가 소유한 Mac과 F100 한 구성에서 확인했습니다. 추가 Mac에서는 첫 연결과 가져오기·저장(1롤·12컷)을 확인했습니다. 다른 케이블과 새 사용자 계정의 첫 실행은 아직 시험하지 않았습니다. [검증 범위](VALIDATION.md)
