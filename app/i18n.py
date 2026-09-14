# SPDX-License-Identifier: GPL-3.0-only
"""Korean/English UI strings; stored language never changes camera or image data."""
import json
import os
from pathlib import Path
import tempfile

EN = {
    '롤 마지막 감도': 'Last recorded ISO',
    '이 롤은 감도를 바꾸지 않았습니다 — ISO도 쓰기': 'I kept the same ISO throughout this roll — also write ISO',
    '기본은 ISO를 쓰지 않습니다. 다중노출 값은 첫 노출 기준입니다.': 'ISO is omitted by default. Multiple-exposure values describe the first exposure.',
    '문서 양식': 'Document template', '문서 언어': 'Document language',
    '화면 언어 따르기': 'Follow interface language', '한국어': 'Korean',
    '기본 양식': 'Built-in template', '개인 Markdown 양식': 'Personal Markdown template',
    '양식 파일 선택': 'Choose template file', '예제 양식 저장': 'Save sample template',
    '미리보기': 'Preview', '적용': 'Apply', '취소': 'Cancel',
    '개인 양식은 이 Mac에만 저장됩니다. 직접 쓰는 메모는 그대로 두세요.': 'Your template stays on this Mac. Keep your own notes and headings as they are.',
    'Markdown 양식': 'Markdown template', '개인 양식 파일을 선택하세요.': 'Choose your personal template file.',
    '지원하지 않는 템플릿 항목입니다. 예제 양식의 항목을 사용하세요: ': 'Unsupported template placeholder. Use a placeholder from the sample: ',
    '템플릿이 너무 큽니다. 256 KB 이하 Markdown 파일을 선택하세요.': 'The template is too large. Choose a Markdown file under 256 KB.',
    '템플릿의 중괄호가 맞지 않습니다. {{항목}} 형식을 확인하세요.': 'Template braces do not match. Check the {{placeholder}} syntax.',
    '예제 양식을 저장했습니다. 편집한 뒤 개인 양식으로 선택하세요.': 'Sample saved. Edit it, then select it as your personal template.',
    '롤 이름에는 글자·숫자·공백·밑줄·하이픈만 사용하세요.': 'Use letters, numbers, spaces, underscores or hyphens in the roll name.',
    '서로 다른 롤의 파일 이름이 같습니다.': 'Two rolls have the same file name. Choose different roll names.',
    '볼트 폴더가 아닙니다.': 'Choose an existing vault folder.',
    '기록 설정': 'Recording settings', '가져오기': 'Import', '스캔에 붙이기': 'Apply to scans',
    '촬영기록': 'Shooting records', '스캔 대응 미리보기': 'Scan matching preview',
    '보관함': 'Library', '롤': 'Roll', '컷': 'Frame', '컷 수': 'Frames', '가져온 날짜': 'Imported', '버전': 'Version',
    '저장된 JSON 열기': 'Open saved JSON', '출력 5종 저장': 'Export five formats',
    '같은 번호의 다른 기록은 별도 버전으로 보관합니다.': 'Different records with the same roll number are kept as separate versions.',
    '롤을 선택한 뒤 스캔 폴더를 여기에 놓으세요. JPEG / TIFF': 'Select a roll, then drop a scan folder here. JPEG / TIFF',
    '순서 뒤집기': 'Reverse order', '시작 컷': 'First frame', '폴더 선택': 'Choose folder',
    '스캔 파일': 'Scan file', '쓸 촬영값': 'Shooting values to write',
    '아직 대응된 파일이 없습니다.': 'No files matched yet.', '확인한 파일에 쓰기': 'Write to matched files',
    '카메라 없이 예제 보기': 'Try a demo without a camera', '도움말': 'Help',
    '먼저 촬영기록에서 롤을 선택하세요.': 'Select a roll in Shooting records first.',
    '처음 가져옴': 'First import', '컷 추가됨': 'Frames added', '같은 번호·다른 기록': 'Different record',
    '확인이 필요합니다': 'Please check', '예제 · 실제 카메라 아님': 'Demo · not a real camera',
    '개발 미리보기 · 합성 예제 1롤 · 카메라 연결은 아직 사용할 수 없습니다.': 'Development preview · one synthetic roll · camera connection is not available yet.',
    '개발 미리보기 · 카메라 연결 미구현 · 저장된 기록을 열어 볼 수 있습니다.': 'Development preview · camera connection is not implemented · you can open saved records.',
    '촬영기록 JSON': 'Shooting-data JSON', '같은 카메라의 기록에 사용할 보관함 이름': 'Library name for records from this camera',
    '내 F100': 'My F100', '출력 폴더를 만들 위치': 'Choose where to create the export folder',
    '한 번에 스캔 폴더 하나를 놓으세요.': 'Drop one scan folder at a time.', '스캔 폴더 선택': 'Choose a scan folder',
    '선택이 바뀌었습니다. 폴더를 다시 선택해 대응표를 갱신하세요.': 'Your selection changed. Select the folder again to refresh the matches.',
    '초': ' s', '보정 ': 'Comp. ', '없음': 'None', '스캔에 촬영정보 쓰기': 'Write shooting data to scans',
    '작업 중': 'Working', '현재 작업이 끝난 뒤 닫아 주세요.': 'Please wait for the current operation to finish before closing.',
    '작업을 완료하지 못했습니다. 다시 선택해 주세요. 상세 내용은 앱 로그에 저장했습니다.': 'The operation could not be completed. Check your selection and try again. Details are in the app log.',
    '{matched}개 대응 · 제외 파일 {files}개 · 미대응 컷 {frames}개 · 지원 외 항목 {ignored}개': '{matched} matched · {files} unmatched files · {frames} unmatched frames · {ignored} unsupported items',
    '{ok}/{total}개 검증 완료 · 결과 기록: {path}': '{ok}/{total} verified · results: {path}',
    '{count}개 파일의 촬영정보를 바꿉니다. 기존 카메라/노출 태그도 변경됩니다.\n원본은 파일명_original로 보관합니다.\n제외 파일: {excluded}\n미대응 컷: {frames}\n계속할까요?': 'Update shooting data in {count} files? Existing camera and exposure tags will be replaced.\nOriginals will be kept as filename_original.\nUnmatched files: {excluded}\nUnmatched frames: {frames}\nContinue?',
    '스캔 폴더를 선택하세요.': 'Select a scan folder.',
    '컷 번호가 중복됩니다. 원본 촬영기록을 확인하세요.': 'Frame numbers are duplicated. Check the original shooting records.',
    '시작 컷 번호가 기록에 없습니다. 목록에 있는 번호를 선택하세요.': 'The starting frame is not in the records. Select a listed frame number.',
    '파일 대응표를 확인하고 쓰기를 선택하세요.': 'Review the matches, then choose Write.',
    '대응된 스캔 파일이 없습니다.': 'There are no matched scan files.',
    '미리보기 이후 파일이 바뀌었습니다. 폴더를 다시 선택하세요.': 'A file changed after the preview. Select the folder again.',
    '기존 원본 백업이 있습니다. 백업을 보관한 뒤 다시 시도하세요: ': 'An original backup already exists. Preserve it before trying again: ',
    '쓰기 전에 파일이 변경되었습니다.': 'The file changed before writing. Select the folder again.',
    '파일 내용이 지원하는 JPEG/TIFF 형식이 아닙니다.': 'The file contents are not a supported JPEG or TIFF image.',
    '쓴 메타데이터를 다시 읽지 못했습니다.': 'The written metadata could not be read back. The original was not replaced.',
    '검증 중 원본 파일이 변경되었습니다.': 'The original changed during verification. Select the folder again.',
    '원본 백업 검증에 실패했습니다.': 'Original backup verification failed. The original was not replaced.',
    '원본 파일이 변경되어 교체하지 않았습니다.': 'The original changed, so it was not replaced.',
    '메타데이터 쓰기 결과를 확인하지 못했습니다: ': 'Metadata writing could not be verified: ',
    '메타데이터 검증 불일치: ': 'Metadata verification mismatch: ',
    '카메라 보관함 이름을 입력하세요.': 'Enter a camera library name.',
    '가져온 원본의 해시가 맞지 않습니다.': 'The imported source checksum does not match. Select the original exported JSON.',
    '언어 설정을 저장하지 못했습니다. 저장 위치의 권한을 확인하세요.': 'The language preference could not be saved. Check permissions for the settings folder.',
}

GENERIC_ERROR = '작업을 완료하지 못했습니다. 다시 선택해 주세요. 상세 내용은 앱 로그에 저장했습니다.'


EN.update({'기록 설정이나 가져오기를 눌러 카메라를 연결하세요.': 'Choose Recording settings or Import to connect your camera.',
 '합성 예제 1롤을 열었습니다. 실제 카메라의 기록은 아닙니다.': 'Opened one synthetic demo roll. These are not records from your camera.',
 '이 안내는 실물 확인된 Prolific F100 데이터 케이블용입니다. 다른 케이블은 별도 검토가 필요합니다.': 'This guide supports the tested Prolific F100 '
                                                                  'data cable. Other cables need separate review.',
 '실제 카메라 연결은 현재 macOS에서만 지원합니다. 예제 보기는 사용할 수 있습니다.': 'Camera connection currently requires macOS. You can still '
                                                     'use the demo.',
 '카메라 연결에 필요한 pyserial이 없습니다. 개발 실행 환경을 확인하세요.': 'pyserial is missing. Check the development environment before '
                                                 'connecting.',
 '지원하지 않는 작업입니다.': 'This operation is not supported.',
 '작업을 취소했습니다. 새 쓰기 명령은 보내지 않았습니다.': 'Cancelled. No new write command was sent.',
 '카메라 연결을 확인하고 있습니다…': 'Checking the camera connection…',
 '{rolls}롤 · {frames}컷을 Mac에 저장했습니다. 저장 위치: {path}': 'Saved {rolls} rolls · {frames} frames to your Mac. '
                                                     'Location: {path}',
 '저장된 촬영기록이 없습니다. 기록 기능은 켜져 있습니다.': 'There are no stored shooting records. Recording is enabled.',
 '저장된 촬영기록이 없습니다. 기록 설정에서 기록 기능을 켜야 앞으로의 촬영이 기록됩니다.': 'There are no stored shooting records. Enable recording in '
                                                      'Recording settings to record future exposures.',
 '이미 같은 설정입니다. 변경하지 않았습니다.': 'These settings are already selected. Nothing was changed.',
 '설정을 확인했습니다. 다음 필름을 넣고 첫 컷으로 진행하면 적용됩니다.': 'Settings verified. They take effect when the next film is loaded and '
                                            'advanced to its first frame.',
 '카메라 기록을 지웠습니다. Mac에 보관한 기록은 남아 있습니다.': 'Camera records erased. The records saved on your Mac remain.',
 '처음 한 번 케이블을 확인합니다. 카메라 전원을 끄고 카메라 쪽과 USB 쪽 케이블을 모두 분리하세요. 다른 USB 장치와 허브는 그대로 두세요. 준비됐나요?': 'First, we need to '
                                                                                             'check your cable. '
                                                                                             'Turn the camera off '
                                                                                             'and disconnect both '
                                                                                             'ends of the cable. '
                                                                                             'Leave other USB '
                                                                                             'devices and hubs '
                                                                                             'unchanged. Ready?',
 '케이블의 USB 쪽만 Mac에 연결하세요. 카메라 쪽은 연결하지 마세요. 준비됐나요?': 'Connect only the USB end to your Mac. Leave the camera end '
                                                    'disconnected. Ready?',
 '이 장치가 직접 확인한 F100 데이터 케이블이 맞나요? 카메라는 아직 분리된 상태여야 합니다. Wi-Fi는 그대로 사용하며 이 케이블 확인을 다음 연결에도 사용합니다.\n포트: {port}': 'Is '
                                                                                                               'this '
                                                                                                               'the '
                                                                                                               'F100 '
                                                                                                               'data '
                                                                                                               'cable '
                                                                                                               'you '
                                                                                                               'have '
                                                                                                               'personally '
                                                                                                               'checked? '
                                                                                                               'The '
                                                                                                               'camera '
                                                                                                               'must '
                                                                                                               'still '
                                                                                                               'be '
                                                                                                               'disconnected. '
                                                                                                               'Wi-Fi '
                                                                                                               'stays '
                                                                                                               'on, '
                                                                                                               'and '
                                                                                                               'this '
                                                                                                               'inspection '
                                                                                                               'will '
                                                                                                               'be '
                                                                                                               'used '
                                                                                                               'for '
                                                                                                               'later '
                                                                                                               'connections.\n'
                                                                                                               'Port: '
                                                                                                               '{port}',
 '카메라가 분리돼 있다면 전원을 끈 상태에서 케이블을 연결한 뒤 전원을 켜세요. Windows VM과 다른 카메라 연결 프로그램은 종료하세요. 준비됐나요?\n포트: {port}': 'If the '
                                                                                                      'camera is '
                                                                                                      'disconnected, '
                                                                                                      'connect '
                                                                                                      'its cable '
                                                                                                      'with the '
                                                                                                      'power off, '
                                                                                                      'then turn '
                                                                                                      'it on. '
                                                                                                      'Close the '
                                                                                                      'Windows VM '
                                                                                                      'and other '
                                                                                                      'camera '
                                                                                                      'connection '
                                                                                                      'programs. '
                                                                                                      'Ready?\n'
                                                                                                      'Port: '
                                                                                                      '{port}',
 '카메라의 필름 카운터가 E인지 직접 확인하세요. 앱은 이 표시를 읽을 수 없습니다. 지금 E가 표시돼 있나요?': 'Check the film counter on the camera yourself. '
                                                                  'The app cannot read this display. Does it show '
                                                                  'E now?',
 '선택한 설정으로 바꿀까요? 다음 필름을 넣고 첫 컷으로 진행하면 적용됩니다.\n선택: {setting}\n보관 위치: {backup}': 'Apply these settings? They take '
                                                                               'effect when the next film is '
                                                                               'loaded and advanced to its first '
                                                                               'frame.\n'
                                                                               'Selection: {setting}\n'
                                                                               'Saved records: {backup}',
 '촬영기록 {frames}컷을 Mac에 보관했습니다. 카메라의 촬영기록을 전부 지울까요? Mac에서 계속 볼 수 있지만 카메라에 다시 넣을 수는 없습니다. 필름의 사진은 지워지지 않습니다.\n보관 위치: {backup}': 'Saved '
                                                                                                                              '{frames} '
                                                                                                                              'frame '
                                                                                                                              'records '
                                                                                                                              'to '
                                                                                                                              'your '
                                                                                                                              'Mac. '
                                                                                                                              'Erase '
                                                                                                                              'all '
                                                                                                                              'shooting '
                                                                                                                              'records '
                                                                                                                              'from '
                                                                                                                              'the '
                                                                                                                              'camera? '
                                                                                                                              'You '
                                                                                                                              'can '
                                                                                                                              'still '
                                                                                                                              'view '
                                                                                                                              'them '
                                                                                                                              'on '
                                                                                                                              'your '
                                                                                                                              'Mac, '
                                                                                                                              'but '
                                                                                                                              'cannot '
                                                                                                                              'put '
                                                                                                                              'them '
                                                                                                                              'back '
                                                                                                                              'into '
                                                                                                                              'the '
                                                                                                                              'camera. '
                                                                                                                              'Photographs '
                                                                                                                              'on '
                                                                                                                              'the '
                                                                                                                              'film '
                                                                                                                              'are '
                                                                                                                              'not '
                                                                                                                              'erased.\n'
                                                                                                                              'Saved '
                                                                                                                              'records: '
                                                                                                                              '{backup}',
 '카메라 확인': 'Camera confirmation',
 '현재 설정은 아래 선택지에 없습니다.': 'The current setting is not one of the choices below.',
 '현재 설정: {setting}': 'Current setting: {setting}',
 '설정 변경은 기록이 비어 있고 카운터가 E일 때만 됩니다. 기록이 있다면 취소하거나 별도로 보관 후 삭제하세요.': 'Settings can change only with empty record '
                                                                   'memory and counter E. If records remain, '
                                                                   'cancel or save and erase them separately.',
 '덮어쓰기를 선택하면 새 롤 하나로 예전 여러 롤의 기록이 사라질 수 있습니다.': 'With overwrite enabled, one new roll can erase records from '
                                                'several older rolls.',
 '카메라 기록 보관 후 전부 삭제…': 'Save and erase all camera records…',
 '선택한 설정 적용…': 'Apply selected settings…',
 '기록 켜기 · Simple · 가득 차면 촬영 중지': 'Record on · Simple · Stop shooting when full',
 '기록 켜기 · Simple · 가득 차면 오래된 기록 덮어쓰기': 'Record on · Simple · Overwrite old records when full',
 '기록 켜기 · Detailed · 가득 차면 촬영 중지': 'Record on · Detailed · Stop shooting when full',
 '기록 켜기 · Detailed · 가득 차면 오래된 기록 덮어쓰기': 'Record on · Detailed · Overwrite old records when full',
 '기록 끄기 · Simple · 덮어쓰기 설정': 'Record off · Simple · Overwrite policy',
 '기록 끄기 · Detailed · 덮어쓰기 설정': 'Record off · Detailed · Overwrite policy',
 '카메라에 기록이 남아 있거나 설정 상태를 확인하지 못했습니다. 가져오기로 기록을 확인하세요. 설정은 바꾸지 않았습니다.': 'Records remain on the camera, or its '
                                                                       'settings state could not be verified. Use '
                                                                       'Import to check the records. Settings '
                                                                       'were not changed.',
 '이전 케이블 확인과 현재 연결이 맞지 않습니다. 다른 USB 장치를 원래대로 연결하거나 도움말의 케이블 다시 확인을 사용하세요.': 'The current connection does not '
                                                                            'match the cable inspection. Restore '
                                                                            'the previous USB connections, or '
                                                                            'choose Check cable again in Help.',
 '작업 완료를 확인하지 못했습니다. 이미 보낸 변경은 적용됐을 수 있습니다. 카메라 전원과 연결을 확인하고 가져오기로 상태를 확인하세요. 자동으로 다시 쓰지 않습니다.': 'Completion '
                                                                                                 'could not be '
                                                                                                 'verified. A '
                                                                                                 'change already '
                                                                                                 'sent may have '
                                                                                                 'taken effect. '
                                                                                                 'Check camera '
                                                                                                 'power and '
                                                                                                 'connections, '
                                                                                                 'then use Import '
                                                                                                 'to check its '
                                                                                                 'state. Writes '
                                                                                                 'are not retried '
                                                                                                 'automatically.',
 '케이블 다시 확인': 'Check cable again',
 '다음 연결에서 케이블을 처음부터 다시 확인할까요? 촬영기록과 이전 확인 기록은 지우지 않습니다.': 'Check the cable from the beginning on the next '
                                                          'connection? Shooting records and earlier inspection '
                                                          'records will be kept.'})

EN.update({'보관 파일을 확인하지 못해 삭제를 중단했습니다. 카메라 기록은 지우지 않았습니다.': 'Deletion stopped because the saved records could not be '
                                                  'verified. Camera records were not erased.',
 '삭제 중단': 'Deletion stopped',
 '현재 보관 폴더에서 {missing}/{total}롤의 저장을 확인하지 못했습니다.\n확인하지 못한 롤 번호: {numbers}\n폴더: {archive}\n\n미리 저장하지 않은 촬영기록은 복구할 수 없습니다. 삭제하지 않았습니다. 파일을 다시 저장하고 확인하세요.': 'Could '
                                                                                                                                                          'not '
                                                                                                                                                          'verify '
                                                                                                                                                          'saved '
                                                                                                                                                          'records '
                                                                                                                                                          'for '
                                                                                                                                                          '{missing}/{total} '
                                                                                                                                                          'rolls '
                                                                                                                                                          'in '
                                                                                                                                                          'the '
                                                                                                                                                          'current '
                                                                                                                                                          'archive '
                                                                                                                                                          'folder.\n'
                                                                                                                                                          'Unverified '
                                                                                                                                                          'roll '
                                                                                                                                                          'numbers: '
                                                                                                                                                          '{numbers}\n'
                                                                                                                                                          'Folder: '
                                                                                                                                                          '{archive}\n'
                                                                                                                                                          '\n'
                                                                                                                                                          'Unsaved '
                                                                                                                                                          'shooting '
                                                                                                                                                          'records '
                                                                                                                                                          'cannot '
                                                                                                                                                          'be '
                                                                                                                                                          'recovered '
                                                                                                                                                          'after '
                                                                                                                                                          'erasing. '
                                                                                                                                                          'Nothing '
                                                                                                                                                          'was '
                                                                                                                                                          'erased. '
                                                                                                                                                          'Save '
                                                                                                                                                          'and '
                                                                                                                                                          'check '
                                                                                                                                                          'the '
                                                                                                                                                          'files '
                                                                                                                                                          'again.',
 'Mac 저장 확인: {verified_rolls}/{total_rolls}롤 · {frames}컷\n보관 폴더: {archive}\n\n미리 저장하지 않은 촬영기록은 복구할 수 없습니다. 카메라의 촬영기록 {total_rolls}롤을 전부 삭제할까요?\n이 폴더의 기록은 Mac에서 볼 수 있지만 카메라에 다시 넣을 수는 없습니다. 필름의 사진은 지워지지 않습니다.': 'Verified '
                                                                                                                                                                                                                 'on '
                                                                                                                                                                                                                 'your '
                                                                                                                                                                                                                 'Mac: '
                                                                                                                                                                                                                 '{verified_rolls}/{total_rolls} '
                                                                                                                                                                                                                 'rolls '
                                                                                                                                                                                                                 '· '
                                                                                                                                                                                                                 '{frames} '
                                                                                                                                                                                                                 'frames\n'
                                                                                                                                                                                                                 'Archive '
                                                                                                                                                                                                                 'folder: '
                                                                                                                                                                                                                 '{archive}\n'
                                                                                                                                                                                                                 '\n'
                                                                                                                                                                                                                 'Unsaved '
                                                                                                                                                                                                                 'shooting '
                                                                                                                                                                                                                 'records '
                                                                                                                                                                                                                 'cannot '
                                                                                                                                                                                                                 'be '
                                                                                                                                                                                                                 'recovered '
                                                                                                                                                                                                                 'after '
                                                                                                                                                                                                                 'erasing. '
                                                                                                                                                                                                                 'Erase '
                                                                                                                                                                                                                 'all '
                                                                                                                                                                                                                 '{total_rolls} '
                                                                                                                                                                                                                 'rolls '
                                                                                                                                                                                                                 'of '
                                                                                                                                                                                                                 'shooting '
                                                                                                                                                                                                                 'records '
                                                                                                                                                                                                                 'from '
                                                                                                                                                                                                                 'the '
                                                                                                                                                                                                                 'camera?\n'
                                                                                                                                                                                                                 'You '
                                                                                                                                                                                                                 'can '
                                                                                                                                                                                                                 'view '
                                                                                                                                                                                                                 'the '
                                                                                                                                                                                                                 'saved '
                                                                                                                                                                                                                 'records '
                                                                                                                                                                                                                 'on '
                                                                                                                                                                                                                 'your '
                                                                                                                                                                                                                 'Mac, '
                                                                                                                                                                                                                 'but '
                                                                                                                                                                                                                 'cannot '
                                                                                                                                                                                                                 'put '
                                                                                                                                                                                                                 'them '
                                                                                                                                                                                                                 'back '
                                                                                                                                                                                                                 'into '
                                                                                                                                                                                                                 'the '
                                                                                                                                                                                                                 'camera. '
                                                                                                                                                                                                                 'Photographs '
                                                                                                                                                                                                                 'on '
                                                                                                                                                                                                                 'the '
                                                                                                                                                                                                                 'film '
                                                                                                                                                                                                                 'are '
                                                                                                                                                                                                                 'not '
                                                                                                                                                                                                                 'erased.',
 'Simple은 셔터·조리개·초점거리·플래시 등 기본 정보만, Detailed는 여기에 렌즈 정보·촬영 모드·측광·보정 등을 더 기록합니다.': 'Simple keeps basic information '
                                                                                  'such as shutter speed, '
                                                                                  'aperture, focal length and '
                                                                                  'flash. Detailed adds lens '
                                                                                  'information, exposure mode, '
                                                                                  'metering, compensation and '
                                                                                  'more.'})

EN.update({'이전에 남겨둔 수정 전 사진이 있습니다. 기존 폴더는 보관하고, 작업할 JPEG/TIFF만 새 폴더로 복사해 선택하세요: ': 'A copy of the photo from before the previous edit already exists. Keep the old folder intact, copy only the JPEG/TIFF photos to a new folder, and select it: '})

EN.update({'사용할 케이블을 확인하고 앱에 등록하겠습니다.\n\n1. 카메라 전원을 끄세요.\n2. 케이블을 카메라와 Mac 양쪽에서 빼세요.\n3. 다른 USB 장치와 허브는 그대로 두세요.\n\n케이블을 양쪽에서 모두 뺐나요?': 'Let’s check and register your cable.\n\n1. Turn the camera off.\n2. Unplug the cable from both the camera and your Mac.\n3. Leave other USB devices and hubs as they are.\n\nHave you unplugged both ends?', '처음 사용하시나요?\n촬영기록을 보려면 ‘가져오기’, 기록 기능을 켜거나 바꾸려면 ‘기록 설정’을 누르세요.\n어느 버튼을 눌러도 처음에는 케이블 연결 방법부터 안내합니다.': 'Getting started\nChoose Import to view shooting records, or Recording settings to enable or change recording.\nEither button guides you through connecting your cable on first use.', '카메라에서 작업이 끝났는지 확인할 수 없습니다.\n설정 변경이나 삭제가 이미 됐을 수 있으니 같은 작업을 다시 누르지 마세요.\n카메라 전원과 케이블을 확인한 뒤, ‘가져오기’로 남아 있는 기록을 확인하세요. 앱이 같은 명령을 다시 보내지는 않습니다.': 'We could not confirm whether the camera finished.\nThe settings change or deletion may already have happened. Do not repeat the action.\nCheck the camera power and cable, then choose Import to check the remaining records. The app will not resend the change or deletion command.', '가져오기를 끝내지 못했습니다.\n카메라 전원과 케이블 연결을 확인한 뒤 ‘가져오기’를 다시 눌러 주세요.\n카메라의 설정이나 촬영기록은 바꾸지 않았습니다.': 'Import could not finish.\nCheck the camera power and cable, then choose Import again.\nNo camera settings or shooting records were changed.', '카메라 상태를 확인하지 못했습니다.\n카메라 전원과 케이블 연결을 확인한 뒤 다시 시작해 주세요.\n설정이나 촬영기록은 바꾸지 않았습니다.': 'We could not check the camera’s status.\nCheck the camera power and cable, then try again.\nNo settings or shooting records were changed.'})


EN.update({'새로 연결된 케이블을 찾지 못했습니다.\n처음 안내가 나올 때 케이블을 Mac에서도 빼고, 다음 안내가 나오면 USB 쪽을 다시 꽂아 주세요.\n카메라 설정이나 촬영기록은 바꾸지 않았습니다.': 'No newly connected cable was found.\nUnplug the cable from your Mac at the first prompt, then reconnect the USB end at the next prompt.\nNo camera settings or shooting records were changed.', '연결 전후에 케이블 이외의 장치 변화가 있거나, 케이블을 찾지 못했습니다. 다른 USB 장치는 그대로 두고 다시 시도하세요.': 'The connection check could not isolate the cable. Leave other USB devices unchanged and repeat the cable check.', '연결 정보가 불완전하거나 서로 맞지 않습니다. 다시 연결을 확인하세요.': 'Device information is incomplete or inconsistent. Repeat the connection check.', '케이블의 통신 포트를 찾지 못했습니다. macOS에서 케이블이 인식됐는지 확인하세요.': 'The cable’s serial port was not found. Check whether macOS recognizes the cable.', '장치 연결 경로를 확인하지 못했습니다.': 'The device connection path could not be verified.'})

EN.update({'롤': 'Roll', '롤 마지막 감도': 'Last recorded ISO', '컷': 'Frame', '셔터': 'Shutter', '조리개': 'Aperture', '초점거리': 'Focal length', '모드': 'Mode', '측광': 'Metering', '노출보정': 'Exposure compensation', '플래시보정': 'Flash compensation', '플래시': 'Flash', '싱크': 'Sync', '다중노출': 'Multiple exposure'})

EN.update({'플래시 발광 시점': 'Flash timing', '선막은 셔터가 열린 뒤, 후막은 닫히기 직전에 발광합니다.': 'Front curtain fires after the shutter opens; rear curtain fires just before it closes.'})

EN.update({'카메라 내부 기록 번호: {number}': 'Camera internal record number: {number}', '저장 폴더 이름': 'Export folder name', '이 위치에 새 폴더를 만듭니다: {path}\n폴더 이름을 정해 주세요.': 'Create a new folder in: {path}\nChoose a folder name.', '폴더 이름에 / 또는 \\를 넣을 수 없습니다. 빈 이름이나 . 또는 ..도 사용할 수 없습니다.': 'Use a non-empty folder name without / or \\. The names . and .. are not allowed.', '같은 이름의 폴더나 파일이 있습니다. 다른 이름을 정해 주세요. 기존 파일은 바꾸지 않습니다.': 'A folder or file with that name already exists. Choose another name. Existing files will not be changed.', '파일을 저장했습니다. 저장 위치: {path}': 'Files saved in: {path}'})

EN.update({'촬영기록을 저장할 위치': 'Where to save shooting records', '선택한 폴더에 저장하지 못했습니다. 기록은 앱 안에 보관돼 있습니다. ‘촬영기록 저장…’으로 다른 위치에 저장해 주세요.': 'Could not save to the selected folder. The records are kept in the app. Use Save shooting records to save them elsewhere.'})

EN.update({'촬영정보 기록을 켜거나 끄고, 저장할 항목을 선택합니다. 설정을 바꾸기 전에 다시 확인합니다.': 'Turn shooting-data recording on or off and choose what to record. Changes require confirmation.', '카메라의 촬영기록을 읽어 선택한 폴더에 저장합니다. 카메라에 있는 기록은 지우지 않습니다.': 'Read shooting records from the camera and save them to your chosen folder. Camera records are not erased.', '이 앱에서 저장한 shooting-data.json 파일을 엽니다. 카메라 없이도 이전 촬영기록을 볼 수 있습니다.': 'Open a shooting-data.json file saved by this app. View earlier records without connecting a camera.', '선택한 롤을 보기용 표, CSV, 원본 값 파일, EXIF 작업용 CSV, 촬영일지로 저장합니다. 저장 위치와 폴더 이름을 고를 수 있습니다.': 'Save the selected roll as a viewing table, CSV, raw-value file, EXIF working CSV and shooting journal. Choose the location and folder name.', '저장할 촬영일지의 모양과 출력 문서의 언어를 고릅니다. 처음에는 기본 양식을 그대로 쓰셔도 됩니다.': 'Choose the shooting-journal layout and document language. The built-in template is ready to use.', '직접 만든 촬영일지 양식을 선택합니다. 처음이라면 ‘예제 양식 저장’으로 견본부터 받아 보세요.': 'Select your own shooting-journal template. Start with Save sample template if this is your first time.', '고쳐 쓸 수 있는 촬영일지 견본을 저장합니다. 글 편집기로 내용을 바꾼 뒤 개인 양식으로 선택하세요.': 'Save an editable journal template. Edit it in a text editor, then select it as your personal template.', '선택한 양식으로 촬영일지가 어떻게 나오는지 봅니다. 아직 파일을 저장하지 않습니다.': 'See how the journal looks with this template. No output file is saved yet.', '다음에 저장하는 문서부터 이 설정을 사용합니다. 이미 저장한 파일은 바꾸지 않습니다.': 'Use these settings for future exports. Files already saved will not change.', '이 창을 닫습니다. 이 창에서 고른 변경은 적용하지 않습니다.': 'Close this window without applying the changes selected here.', '먼저 촬영기록을 Mac에 저장하고 확인한 뒤 삭제 여부를 묻습니다. 이 버튼만 눌러서는 지우지 않습니다.': 'Save and check the records on your Mac first, then ask whether to erase. Clicking this button alone does not erase records.', '저장한 촬영기록 열기': 'Open saved shooting records', '카메라 촬영기록 삭제…': 'Erase camera shooting records…', '기본 양식으로도 바로 사용할 수 있습니다. 문서 언어는 출력 파일의 언어를, 개인 양식은 Markdown 촬영일지의 모양을 바꿉니다. 카메라 설정과 이미 저장한 파일은 바꾸지 않습니다.': 'The built-in template is ready to use. Document language affects exported files; a personal template changes the Markdown journal layout. Neither changes camera settings or existing files.', '먼저 촬영기록을 Mac에 저장하고 확인합니다. 그다음 삭제 여부를 묻습니다. 확인하기 전에는 지우지 않습니다.': 'Records are saved and checked on your Mac first. You are then asked whether to erase them. Nothing is erased before confirmation.'})

EN.update({'카메라 기록 전부 삭제':'Erase all camera records','화면 언어를 한국어와 영어로 바꿉니다.':'Switch the interface between Korean and English.'})

EN.update({'촬영기록 저장…':'Save shooting records…', '저장할 형식 선택':'Choose file formats',
           '저장할 파일을 골라 주세요.':'Choose the files to save.',
           '원본 데이터 보관':'Keep original data',
           '원본 데이터 보관은 앱이 읽은 값을 그대로 남기는 파일입니다. 보통 열어볼 필요는 없습니다.':'Original data keeps exactly what the app read. You normally do not need to open this file.',
           '보기 좋은 HTML 표':'Readable HTML table', '촬영일지 Markdown':'Shooting journal (Markdown)',
           '일반 CSV 표':'Regular CSV table', 'EXIF 작업용 CSV':'EXIF working CSV',
           '선택한 형식으로 저장':'Save selected formats', '파일 형식을 하나 이상 선택하세요.':'Select at least one file format.',
           '선택한 롤을 원하는 파일 형식으로 저장합니다. 저장 위치와 폴더 이름을 고를 수 있습니다.':'Save the selected roll in the file formats you choose. You can choose the location and folder name.',
           '원본 데이터 파일':'Original data file',
           '원본 데이터 보관은 앱이 읽은 값을 그대로 남기며, 나중에 앱에서 기록을 다시 열 때 씁니다.':'Original data keeps exactly what the app read and lets the app reopen the record later.',
           '브라우저에서 읽기 좋은 촬영정보 표입니다.':'A shooting-information table that is easy to read in a browser.',
           '글과 표로 된 롤별 촬영일지입니다.':'A roll-by-roll journal made of text and tables.',
           '앱이 읽은 원본값과 해석값을 그대로 보관합니다. 나중에 앱에서 다시 열 때 씁니다.':'Keeps the raw and interpreted values exactly as read. The app uses it to reopen the record later.',
           'Numbers·Excel에서 열어 편집할 수 있는 표입니다.':'A table you can open and edit in Numbers or Excel.',
           '스캔 파일에 촬영정보를 붙일 때 쓰는 작업용 표입니다.':'A working table for adding shooting data to scan files.',
           '감도는 마지막 노출 컷 기준입니다.':'ISO is from the last exposed frame.',
           '다중노출은 첫 노출 값만 표시합니다.':'Multiple exposure shows the first exposure only.',
           '일반은 선막, 후막은 셔터가 닫히기 직전 발광입니다.':'Normal is front curtain; rear is just before the shutter closes.',
           '원본 데이터 보관 파일에서 원시값과 해석값을 함께 확인할 수 있습니다.':'The original-data file keeps raw and interpreted values together.'})
EN.update({'일반은 선막, 후막은 셔터가 닫히기 직전 발광합니다.':'Normal is front curtain; rear is just before the shutter closes.'})

class Translator:
    def __init__(self, home):
        self.path = Path(home) / 'preferences.json'
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.language = value.get('language', 'ko') if isinstance(value, dict) else 'ko'
        except (OSError, ValueError):
            self.language = 'ko'
        if self.language not in ('ko', 'en'):
            self.language = 'ko'

    def text(self, key, **values):
        text = EN.get(key, key) if self.language == 'en' else key
        return text.format(**values) if values else text

    def error(self, message):
        localized = getattr(message, 'localized', None)
        if callable(localized):
            return localized(self.language)
        message = str(message)
        if message in EN:
            return self.text(message)
        for key in EN:
            if key.endswith(': ') and message.startswith(key):
                return self.text(key) + message[len(key):]
        return self.text(GENERIC_ERROR)

    def set_language(self, language):
        if language not in ('ko', 'en'):
            raise ValueError('Unsupported language')
        self.update_preferences({'language': language})
        self.language = language

    def preferences(self):
        try:
            settings = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            settings = {}
        return settings if isinstance(settings, dict) else {}

    def update_preferences(self, updates):
        settings = self.preferences()
        settings.update(updates)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.preferences-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(settings, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
