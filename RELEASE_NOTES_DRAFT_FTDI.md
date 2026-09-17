# Neo Film Bridge v0.7.2-preview-r10 (초안) — USB-serial 어댑터 지원 확대

> **초안입니다.** 태그·GitHub Release는 아직 만들지 않았습니다. 커밋·푸시도 하지 않았습니다. 이 문서는 검토용 초안이며, 승인 후 그대로 발행하거나 필요시 다듬어 발행합니다.

이번 릴리스는 새 기능이 아니라 실물 하드웨어 시험 범위를 넓히기 위한 최소 유지보수입니다.

## A. 변경

케이블 확인(USB admission) 절차가 인식하는 어댑터 범위가 **Prolific PL2303(067B:2303) 정확 일치 하나**에서, **Prolific(벤더 ID `0x067b`) 및 FTDI(벤더 ID `0x0403`) 두 vendor family**로 늘었습니다.

연결 경로는 다음과 같습니다.

```
Nikon F100
→ Nikon MC-31 (RS-232 데이터 케이블)
→ 지원되는 Serial-to-USB 어댑터
→ Mac
```

MC-31과 USB-serial 어댑터는 서로 다른 두 장치입니다 — MC-31 자체가 USB 장치로 인증되는 것이 아니며, macOS와 이 앱이 USB 장치로 관찰하는 것은 어댑터입니다.

**vendor match는 최종 승인이나 자동 신뢰가 아니라, admission 절차에 진입할 수 있는 사전 조건일 뿐입니다.** vendor match 이후에는 기존 fail-closed 검증이 전혀 완화 없이 그대로 적용됩니다: 연결 전후 USB 스냅샷 대조, 새 USB 장치·새 `/dev/cu.*` serial path 검출과 그 정확성·유일성 검사, fingerprint sealing, topology binding, 사용자의 명시적 물리 확인, 승인 기록과 재연결 상태 비교 후 불일치 시 STOP, 무관한 USB 변화 시 STOP, snapshot 불완전 시 STOP, 기존 network-isolation exception 범위 유지. 정확한 요약: **Prolific과 FTDI vendor family를 admission 진입 대상으로 추가·통합하여 사전 허용 범위는 확대됐지만, admission 이후의 fail-closed 조건은 하나도 완화하지 않았습니다.**

이 vendor allowlist 자체가 실제로 필요한 보안 경계인지도 별도로 독립 감사했습니다. 결론: vendor 검사는 의도적으로 vendor_id를 위조하는 공격자에게는 실질적 장벽이 아니며(펌웨어에서 자유롭게 설정 가능), 실제 방어는 전부 vendor와 무관한 downstream 검증(스냅샷 diff, fingerprint, topology, 사용자 확인)에서 나옵니다. 다만 감사 중 "새 USB 장치 1개 + 새 `/dev/cu.*` 1개"라는 **개수 일치만으로 둘을 같은 물리 장치로 간주**하는, IOKit 레지스트리 증거에 기반하지 않은 기존 설계상의 약점을 발견했습니다(관련 회귀 테스트: `mac-connection/test_f100_offline_usb_gate.py::VendorAllowlistSecurityAuditTests`). 이 약점은 vendor allowlist 유지·제거 여부와 무관하게 이미 존재하던 것이며, 이번 r10에서 새로 만든 것이 아닙니다. vendor allowlist를 제거해도 나아지지 않으므로, 이 결합을 더 강화하기 전까지는 현재의 067b/0403 정책을 그대로 유지하기로 했습니다(일반화하지 않음).

CH340/CH341, CP210x 등 다른 USB-serial 칩셋은 이번에도 지원하지 않습니다. 어느 vendor든 "지원 대상이라서" 자동으로 승인되는 경로는 없으며, 사용자가 '케이블 다시 확인' 절차를 전부 거쳐야 합니다.

안내 문구도 "실물 확인된 Prolific F100 데이터 케이블"이라는 Prolific 전용 표현에서 "지원되는 USB-serial 어댑터(Prolific PL2303 또는 FTDI 계열)"로 바뀌었습니다. 최초 USB 연결 안내도 다음 순서를 명확히 하도록 다듬었습니다: (1) USB 쪽 연결 → (2) macOS가 액세서리 연결 허용을 물으면 먼저 허용 → (3) 장치 연결 완료 → (4) 그다음 앱 창에서 진행 → (5) 이 단계에서는 카메라 쪽은 아직 연결하지 않음. 임의 sleep/지연은 추가하지 않았습니다.

## B. 2026-09-17 실물시험

Nikon F100 → 정품 Nikon MC-31 RS-232 데이터 케이블 → FTDI 기반 Serial-to-USB 어댑터 → Apple Silicon Mac 구성으로 개발자 소유 장비에서 실제 통신을 수행했습니다.

확인된 결과:
- FTDI admission 성공(admission 보고서 `PASS`, 전달 게이트 `PASS_FOR_MANUAL_UTM_FORWARDING_REVIEW`)
- 카메라 연결 성공
- 46번 롤 · 25컷 촬영기록 가져오기 성공
- 카메라 기록 삭제 성공(`outcome: success`)

**삭제 성공은 EP/NP 설정 쓰기 성공과 같은 의미가 아닙니다.** 이번 실물시험에서 확인한 write 동작은 삭제(EP)이며, 기록 설정 변경(NP)은 별도로 실물시험하지 않았습니다.

## C. 검증 범위의 한계

- 기존 Prolific PL2303(067B:2303) 경로: 기존에 이미 실물검증 이력이 있습니다.
- FTDI 기반 어댑터 + 정품 MC-31: 2026-09-17 위 구성으로 실물검증을 완료했습니다.
- Prolific 0x067b vendor-family 확대 중 067B:2303 이외 제품: 이번 변경에서는 **offline 검증만** 수행했고 개별 실물검증은 하지 않았습니다.
- 다른 FTDI 제품(FT230X 등): vendor-family admission 대상이라는 사실과 개별 제품의 실물검증 여부는 서로 다릅니다 — 실물검증한 것은 FT232R 계열 제품 하나뿐입니다.

## D. 카메라 명령 계층

F100 read protocol, EP/NP/DP write 명령, 촬영정보 해석, export, HTML 보고서 등 카메라 통신·데이터 처리 로직은 이번 변경에서 전혀 건드리지 않았습니다. 오직 USB 케이블 확인 절차와 관련 안내 문구·문서·테스트만 수정했습니다.

## E. Offline 회귀

r10 후보 변경(PHASE 1–3 USB↔serial ancestry 하드닝 + 이번 연결 안내 UX 수정 포함)을 현재 작업트리에서 최종 재실행한 결과:

- `tests/`: 166 PASS (기존 162 + 이번 연결 안내 UX 의미 검증 테스트 4개 신규 추가)
- `mac-connection/`: 57 PASS (PHASE 2 ancestry hardening 회귀 포함, 기존 44에서 증가)
- `mac-client/`: 95 PASS, 1 SKIP(`test_cable_id_cli_uses_shared_identification_without_serial_access` — 연구용 케이블 식별 도구가 공개 소스 패키지에서 제외되어 있다는 기존·무관 skip)
- 합계: **318 PASS / 0 FAIL / 1 기존·무관 SKIP**
- 저장소 전체 Python 컴파일 검사: 통과
- `MANIFEST.sha256`: r9 커밋 기준이므로 이번 r10 변경 파일 18개(README 양쪽, app/camera.py·connection.py·i18n.py·nfbridge.py, docs/VALIDATION.md, PHASE 2 하드닝 관련 mac-connection 파일 6개, tests 3개, 그리고 이 세션과 무관한 기존 미커밋 변경인 RELEASE_CHECKLIST.md)에서 예상대로 불일치 — 실제 커밋 시점에 재생성 필요. 예상 밖의 파일 불일치는 없었음.
- golden 비교(`empty_roll`/`simple_one_roll`/`detailed_two_rolls`): 3/3 통과

## F. 지원 범위

실행 파일 대상은 Apple Silicon이며 macOS 14.0 이상을 declares합니다. 앱은 ad-hoc 서명됐고 Apple 공증은 받지 않았습니다 — 이 상태는 이번 변경으로 바뀌지 않았습니다.

## G. USB↔serial ancestry 하드닝과 실물 재검증

vendor allowlist 자체가 필요한 보안 경계인지 감사(위 A절)하는 과정에서 발견된, "새 USB 장치 1개 + 새 `/dev/cu.*` 1개"라는 개수 일치만으로 같은 물리 장치라고 간주하던 기존 설계상의 약점을 실제로 하드닝했습니다.

두 실물 어댑터(Prolific, FTDI)에서 각각 별도로 수집한 IORegistry 증거를 비교한 결과, 둘 다 동일한 클래스 계층을 가졌습니다:

```
IOUSBHostDevice → IOUSBHostInterface → IOUserSerial → IOSerialBSDClient
```

(`IOUserSerial`의 드라이버 이름만 `AppleUSBPLCOM`/`AppleUSBFTDI`로 다르고, 클래스는 공통입니다.) 이를 근거로 "candidate `/dev/cu.*` 경로는 candidate USB 장치 자신의 자손 `IOSerialBSDClient` 노드에 `IORegistryEntryID`로 귀속되어야 한다"는 드라이버 이름에 의존하지 않는 검사를 추가했습니다(`f100_offline_usb_gate.py::_bind_candidate_serial_ancestry()`, `connection.inspect()`/`connection.prepare()`에 배선). 기존 검사(스냅샷 대조·fingerprint·topology·사용자 확인·재연결 검증 등)는 하나도 완화·삭제하지 않았고, 이 검사는 그 위에 추가된 독립 검사입니다.

이후 실제 하드웨어로 이 하드닝을 재검증했습니다(read-only import만, EP/NP/erase 없음):

| | Prolific | FTDI |
| --- | --- | --- |
| VID:PID | `0x067b:0x2303` | `0x0403:0x6001` |
| `/dev/cu.*` | `/dev/cu.usbserial-1110` | `/dev/cu.usbserial-FTESX9JU` |
| ancestry 검증 | `candidate_serial_ancestry_verified: true` | `candidate_serial_ancestry_verified: true` |
| 재연결 검증 | 4/4 `MATCHED_PREVIOUS_CABLE` | 3/3 `MATCHED_PREVIOUS_CABLE` |
| read-only 통신 | 성공 | 성공 |

당시 F100은 사용자가 이미 촬영기록을 삭제해 둔 상태였으므로, 성공한 읽기 결과는 `mode: "detailed"`(기록 기능 켜짐), `roll_count: 0, rolls: []`입니다 — 빈 기록을 오류로 오인하지 않고 정상 처리했음을 저장된 `shooting-data.json`으로 직접 확인했습니다.

7번의 재연결+읽기 시도 중 3번에서 `MQ: no response within 40s`가 발생했습니다. 해당 세션들도 admission·ancestry·재연결 검증은 모두 통과(`report.json`이 여전히 `MATCHED_PREVIOUS_CABLE`)했고, 실패는 그 이후 실제 시리얼 I/O 단계였습니다. 사용자가 일부 시도에서 F100 전원을 안내보다 늦게 켠 것으로 확인됐고 증상과 일치하므로, 이번 증거만으로 프로토콜/타임아웃 결함으로 확정하지 않았습니다. **통신 코드나 타임아웃 값은 수정하지 않았습니다.** 대신 아래 H절의 안내 문구를 수정해 전원 켜는 순서를 더 명확히 했습니다.

vendor allowlist 자체는 이번 하드닝으로 제거하지 않았습니다(아래 I절).

## H. 연결 안내 문구 수정

실물시험에서 발견된 두 가지 연결 순서 혼동을 안내 문구에서 제거했습니다(문구만 수정, admission 로직·스냅샷 수집 시점·시리얼 open 시점은 변경하지 않음):

1. **최초 USB 연결 안내**: macOS가 새 USB-serial 액세서리에 대해 별도 연결 허용을 물을 수 있다는 점과, 그 허용을 먼저 끝낸 뒤에만 NFBridge에서 '예'를 눌러야 한다는 순서를 명시했습니다.
2. **F100 전원 연결 안내**: "전원을 끈 상태에서 케이블 연결 → 전원 켜기 → **켜진 것을 확인한 뒤에만** '예'" 순서를 명시했습니다. 이전 문구는 전원을 켜기 전에 '예'를 누를 수 있는 여지가 있었고, 이번 실물시험의 일부 MQ 타임아웃 시도와 증상이 일치합니다.

sleep/polling 지연 추가, macOS 보안 프롬프트 우회, 자동 확인, 사용자 명시적 확인 절차 제거 — 전부 하지 않았습니다.

## I. vendor allowlist — 최종 결정

이전 초안에 남아 있던 연구 방향(HARDEN_THEN_REMOVE)에 대한 이번 r10의 실제 결정을 명확히 합니다: **HARDEN은 완료했고(G절), REMOVE는 진행하지 않습니다.** 현재 실사용 요구는 Prolific과 FTDI 두 경로뿐이며, ancestry 하드닝이 기술적으로 다른 vendor도 안전하게 걸러낼 수 있다 하더라도 그것이 이번 릴리스에서 지원 범위를 넓힐 이유는 아닙니다. CH340/CH341, CP210x 등 다른 칩셋 추가, vendor allowlist 자체 제거 — 둘 다 이번 r10 범위에 포함하지 않았습니다. ancestry 하드닝은 vendor 정책을 대체하는 것이 아니라 그 위에 추가된 독립적인 검증으로 유지합니다.

---

[English draft](RELEASE_NOTES_DRAFT_FTDI.en.md)
