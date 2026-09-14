# 저장량 계산 / Capacity estimate

## 한국어

Simple은 컷당 5바이트, Detailed는 컷당 13바이트입니다. 각 롤에는 5바이트가 더 붙고 전체 데이터 앞에는 1바이트가 있습니다. 이 크기는 촬영기록을 읽어 확인했습니다. 메모리에 들어가는 사진 수가 아니라 **촬영정보의 저장량**입니다. 사진 이미지는 저장하지 않습니다.

Detailed 메모리 채우기 시험에서는 43개 롤 묶음에 1,103컷을 저장한 뒤 FUL이 표시됐습니다. 컷 수를 36으로 나누면 **약 30.6롤(30롤 + 23컷)**입니다. 36컷 필름으로 채운 별도 시험은 아닙니다.

Simple 예상은 같은 저장 공간을 쓴다는 가정으로 계산합니다. Detailed에서 실제로 저장된 전체 데이터 14,555바이트를 계산의 기준으로 잡습니다. 이것이 카메라의 정확한 메모리 상한이라는 뜻은 아닙니다. 아직 모르는 내부 예약 공간이나 모드별 관리 방식이 있을 수 있습니다.

36컷으로 묶인 N컷의 Simple 촬영기록 크기:

`1 + 5 × N + 5 × ceil(N / 36)` 바이트

이 기준에서 2,831컷은 14,551바이트, 그 다음 컷은 14,556바이트입니다. 따라서 사용자 안내에는 **약 2,830컷·36컷 기준 약 78.6롤 예상**으로 반올림해 씁니다. 78개의 완전한 36컷 롤과 다음 롤의 일부에 해당하며, 79롤을 끝까지 저장한다는 뜻은 아닙니다. Simple로 실제 메모리를 가득 채우는 시험은 하지 않았습니다. 롤을 짧게 나누면 롤마다 붙는 정보가 늘어 저장할 수 있는 컷 수가 줄 수 있습니다.

## English

Measured record sizes are 5 bytes per Simple frame and 13 per Detailed frame, plus 5 bytes per roll and one global byte. These are **shooting-information records**, not image storage.

One Detailed full-memory test stored 1,103 frames across 43 roll containers before FUL. Dividing the frame count by 36 gives **about 30.6 rolls (30 rolls plus 23 frames)**. This was not a separate test using 36-exposure rolls.

For the Simple estimate, assume the same storage budget and use the 14,555-byte payload successfully stored in the Detailed test as a calculation baseline. It is not an established exact memory limit; internal reservations or mode-specific storage rules remain uncertain.

For N frames grouped into 36-exposure rolls, the predicted Simple payload is:

`1 + 5 × N + 5 × ceil(N / 36)` bytes.

2,831 frames need 14,551 bytes; the next frame needs 14,556. We round this to **about 2,830 frames, or 78.6 rolls of 36 exposures**. That means 78 complete rolls and part of the next, not 79 complete rolls. Simple capacity has not been tested to full memory. More short rolls may fit fewer total frames because each roll adds overhead.
