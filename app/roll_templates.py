# SPDX-License-Identifier: GPL-3.0-only
"""Data-only Markdown templates. Placeholders are substituted once; never evaluated."""
import re
from pathlib import Path

# Blank sample structure, shared with permission; no personal roll records.
SAMPLE = '{{frontmatter}}\n\n# Roll Log — {{roll_id}}\n\n## Basic\n\n| Item | Value |\n|---|---|\n| Roll ID | {{roll_id}} |\n| Camera / lenses | {{camera}} / {{lenses}} |\n| Film / EI | {{film}} / {{iso}} |\n| Process / lab | {{process}} / {{lab}} |\n| Scan |  |\n| Dates | {{shooting_date}} |\n\n## Purpose\n\n- \n\n## My notes\n\n- Subject:\n- Intention:\n\n## Review after scanning\n\nThree strongest frames:\n- 1:\n- 2:\n- 3:\n\nKeep / record:\n- \n\nTechnical notes:\n- \n\nRoll reflection:\n- \n\nOne thing to change next time:\n- \n\n## Frames\n\n{{frames_table}}\n'
SAMPLE_KO = '{{frontmatter}}\n\n# Roll Log — {{roll_id}}\n\n## Basic\n\n| 항목 | 내용 |\n|---|---|\n| 롤 ID | {{roll_id}} |\n| 바디 / 렌즈 | {{camera}} / {{lenses}} |\n| 필름 / EI | {{film}} / {{iso}} |\n| 현상 / 현상소 | {{process}} / {{lab}} |\n| 스캔 |  |\n| 기간 | {{shooting_date}} |\n\n## 목적\n\n- \n\n## 촬영 중 메모\n\n- 피사체:\n- 의도:\n\n## 스캔 후 리뷰\n\n강한 컷 3:\n- 1:\n- 2:\n- 3:\n\n보류 / 기록:\n- \n\n기술 메모:\n- \n\n롤 회고:\n- \n\n다음에 바꿀 한 가지:\n- \n\n## 프레임 로그 (카메라 기록)\n\n{{frames_table}}\n'

def sample(language='en'):
    if language not in ('ko', 'en'):
        raise ValueError('Unsupported sample language')
    return SAMPLE_KO if language == 'ko' else SAMPLE


MAX_TEMPLATE_BYTES = 256 * 1024
TOKEN = re.compile(r'\{\{(.*?)\}\}', re.DOTALL)
FIELDS = frozenset(('frontmatter', 'frames_table', 'frame_sections', 'roll_id', 'camera', 'film',
                    'iso', 'process', 'lab', 'lenses', 'frame_count', 'roll_number', 'record_mode',
                    'date', 'date_source', 'shooting_date', 'imported', 'film_yaml', 'roll_id_yaml'))


def read_template(path):
    path = Path(path).expanduser()
    with path.open('rb') as handle:
        raw = handle.read(MAX_TEMPLATE_BYTES + 1)
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise ValueError('템플릿이 너무 큽니다. 256 KB 이하 Markdown 파일을 선택하세요.')
    text = raw.decode('utf-8-sig')
    validate(text)
    return text


def validate(text):
    for match in TOKEN.finditer(text):
        if match.group(1).strip() not in FIELDS:
            raise ValueError('지원하지 않는 템플릿 항목입니다. 예제 양식의 항목을 사용하세요: ' + match.group(1).strip())
    if '{{' in TOKEN.sub('', text) or '}}' in TOKEN.sub('', text):
        raise ValueError('템플릿의 중괄호가 맞지 않습니다. {{항목}} 형식을 확인하세요.')


def render(text, context):
    validate(text)
    return TOKEN.sub(lambda match: str(context[match.group(1).strip()]), text)
