# Neo Film Bridge v0.7.2 preview r10 — FTDI 어댑터 지원, USB↔serial ancestry 하드닝, 연결 안내 개선

이번 릴리스는 새 기능이 아니라 실물 하드웨어 지원 범위를 넓히고, 그 과정에서 발견한 admission 설계상의 약점을 하드닝한 최소 유지보수입니다.

[English](RELEASE_NOTES.en.md)

## 지원 어댑터 확대

케이블 확인(USB admission) 절차가 인식하는 어댑터 범위가 **Prolific PL2303(067B:2303) 정확 일치 하나**에서, **Prolific(벤더 ID `0x067b`) 및 FTDI(벤더 ID `0x0403`) 두 vendor family**로 늘었습니다.

연결 경로는 다음과 같습니다.

```
Nikon F100
→ Nikon MC-31 (RS-232 데이터 케이블)
→ FTDI 기반 Serial-to-USB 어댑터 (또는 Prolific 어댑터)
→ Mac
```

MC-31과 Serial-to-USB 어댑터는 서로 다른 두 장치입니다 — MC-31 자체는 USB 장치가 아니며, macOS와 이 앱이 USB identity로 관찰·검증하는 대상은 어댑터입니다. 실측 FTDI 값은 벤더 ID `0x0403`, 제품 ID `0x6001`이며, 특정 제조사·모델의 브랜드명은 지원 제품명으로 쓰지 않습니다 — "FTDI 기반 Serial-to-USB 어댑터"로 통칭합니다.

**vendor match는 최종 승인이나 자동 신뢰가 아니라, admission 절차에 진입할 수 있는 사전 조건일 뿐입니다.** vendor match 이후에는 기존 fail-closed 검증(연결 전후 USB 스냅샷 대조, fingerprint sealing, topology binding, 사용자의 명시적 물리 확인, 재연결 상태 비교, 무관한 USB 변화 시 STOP, network-isolation exception 범위)이 전혀 완화 없이 그대로 적용됩니다. CH340/CH341, CP210x 등 다른 USB-serial 칩셋은 이번에도 지원하지 않으며, vendor allowlist 자체를 제거하지도 않았습니다 — 실제 사용 요구가 Prolific과 FTDI 두 경로뿐이기 때문입니다.

## USB↔serial ancestry 하드닝

FTDI 지원을 추가하는 과정에서, vendor allowlist 자체가 실제로 필요한 보안 경계인지를 독립적으로 감사했습니다. 그 결과 vendor 검사는 의도적으로 vendor_id를 위조하는 공격자에게는 실질적 장벽이 아니라는 점과 함께, 기존 admission 설계의 진짜 결함을 발견했습니다: "새 USB 장치 1개 + 새 `/dev/cu.*` 경로 1개"라는 **개수 일치만으로 둘을 같은 물리 장치로 간주**하고 있었고, 그 serial 경로가 실제로 candidate USB 장치에서 생성됐다는 IOKit 레지스트리 증거는 확인하지 않았습니다.

Prolific과 FTDI 두 실물 어댑터에서 각각 독립적으로 수집한 IORegistry 증거를 비교한 결과, 둘 다 동일한 클래스 계층을 가졌습니다:

```
IOUSBHostDevice → IOUSBHostInterface → IOUserSerial → IOSerialBSDClient
```

(`IOUserSerial`의 드라이버 이름만 Prolific은 `AppleUSBPLCOM`, FTDI는 `AppleUSBFTDI`로 다르고, 클래스는 공통입니다. 보안 판정은 이 드라이버/벤더 문자열에 의존하지 않습니다.) 조사 중 `ioreg -a -r -c IOUSBHostDevice`로 자손을 통해 도달한 `IOSerialBSDClient`에는 `IOCalloutDevice`/`IODialinDevice` 속성이 빠질 수 있다는 macOS 동작을 실측으로 확인해, 별도의 read-only 명령(`ioreg -a -r -c IOSerialBSDClient`)을 추가하고 `IORegistryEntryID`로 두 결과를 결합했습니다. 이 하드닝 전용 collector는 serial port를 열지 않고, F100 프로토콜을 실행하지 않으며, 카메라에 어떤 명령도 보내지 않습니다.

이를 근거로 다음 불변식을 추가했습니다: **candidate `/dev/cu.*` 경로는 candidate USB 장치 자신의 자손 `IOSerialBSDClient` 노드에 `IORegistryEntryID`로 귀속되어야 한다.** 기존 검사(스냅샷 대조·fingerprint·topology·사용자 확인·재연결 검증 등)는 하나도 완화·삭제하지 않았으며, 이 검사는 그 위에 추가된 독립 검사입니다.

## 실물 재검증 (2026-09-17)

하드닝된 admission 경로를 실제 Prolific·FTDI 어댑터로, 각각 단독 연결 상태에서, read-only 가져오기만으로 재검증했습니다(EP/NP/erase 없음).

| | Prolific | FTDI |
| --- | --- | --- |
| VID:PID | `0x067b:0x2303` | `0x0403:0x6001` |
| ancestry 검증 | PASS | PASS |
| 재연결 검증 | 4/4 `MATCHED_PREVIOUS_CABLE` | 3/3 `MATCHED_PREVIOUS_CABLE` |
| F100 read-only 통신 | 성공 | 성공 |

합계 재연결 검증 7/7 통과, 두 어댑터 계열 모두 실제 F100과의 read-only 통신에 성공했습니다. 당시 F100은 사용자가 이미 촬영기록을 삭제해 둔 상태였으므로, 성공한 읽기 결과는 `mode: "detailed"`(기록 기능 켜짐), `roll_count: 0, rolls: []`입니다 — 빈 기록을 오류로 오인하지 않고 정상 처리했습니다.

7회의 재연결+읽기 시도 중 3회에서 `MQ: no response within 40s`가 발생했습니다. 정확한 범위: admission 실패도, ancestry 실패도, 재연결 실패도 아니었습니다 — 해당 세션의 admission 기록도 여전히 `MATCHED_PREVIOUS_CABLE`이었고, 실패는 그 이후 실제 시리얼 I/O에서 MQ 응답을 기다리는 단계였습니다. 이 시도들에서 사용자가 F100 전원을 안내보다 늦게 켠 것으로 확인됐고 증상과 일치하지만, 이 관찰만으로 프로토콜이나 타임아웃 결함이라고 단정하지는 않습니다 — 원인을 사용자 조작으로 과도하게 확정하지도 않습니다. **이번 릴리스에서 통신 코드·타임아웃 값·재시도 로직은 전혀 수정하지 않았습니다.**

## 연결 안내 개선

실물시험에서 연결 순서를 혼동할 수 있는 지점 두 곳을 안내 문구로만 고쳤습니다(로직·타이밍·프로토콜 변경 없음):

1. **최초 USB 연결**: USB 쪽 연결 → macOS가 액세서리 연결 허용을 물으면 먼저 허용 → 연결 완료 확인 → 그 다음에만 '예' → 카메라 쪽은 아직 연결하지 않음, 순서를 명시했습니다.
2. **F100 전원 연결**: F100 전원 OFF 상태에서 케이블 연결 → F100 전원 ON → 켜진 것을 확인 → 그 다음에만 '예', 순서를 명시했습니다. 이전 문구는 전원을 켜기 전에 '예'를 누를 수 있는 여지가 있었고, 위 MQ 타임아웃 시도들과 증상이 일치합니다.

sleep/polling 지연 추가, macOS 보안 프롬프트 우회, 자동 확인, 사용자 명시적 확인 절차 제거는 전혀 하지 않았습니다. 한국어·영어 안내에 동일한 의미가 반영됐습니다.

## 검증 범위의 한계

- Prolific PL2303(067B:2303): 기존 실물검증 이력에 더해 이번 read-only ancestry/reconnect 재검증까지 완료.
- FTDI 기반 어댑터(0403:6001) + 정품 MC-31: 이전 read+erase 실물시험과 이번 read-only ancestry/reconnect 재검증 모두 완료.
- Prolific 0x067b vendor-family 확대 중 067B:2303 이외 제품, 다른 FTDI 제품(FT230X 등): **offline 검증만** 수행했고 개별 실물검증은 하지 않았습니다.
- CH340/CH341, CP210x 등 다른 칩셋: 지원하지 않으며 이번에도 검토하지 않았습니다.

## 카메라 명령 계층

F100 read protocol, EP/NP/DP write 명령, 촬영정보 해석, export, HTML 보고서 등 카메라 통신·데이터 처리 로직은 이번 변경에서 전혀 건드리지 않았습니다.

## Offline 회귀

- `tests/`: 166 PASS
- `mac-connection/`: 57 PASS
- `mac-client/`: 95 PASS, 1 SKIP(연구용 케이블 식별 도구가 공개 소스 패키지에서 제외되어 있다는 기존·무관 skip)
- 저장소 전체 Python 컴파일 검사: 통과
- golden 비교(`empty_roll`/`simple_one_roll`/`detailed_two_rolls`): 3/3 통과
- `MANIFEST.sha256`: 115/115 통과

## 지원 범위

실행 파일 대상은 Apple Silicon이며 macOS 14.0 이상을 declares합니다. 앱은 ad-hoc 서명됐고 Apple 공증은 받지 않았습니다 — 이 상태는 이번 변경으로 바뀌지 않았습니다.
