# SPDX-License-Identifier: GPL-3.0-only
"""Append-only roll versions. Camera namespaces are explicit, never inferred from roll number."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class Library:
    def __init__(self, root):
        self.root = Path(root)

    def entries(self):
        entries = []
        for path in sorted(self.root.glob('*/*.json')):
            value = json.loads(path.read_text(encoding='utf-8'))
            value['_path'] = str(path)
            entries.append(value)
        return entries

    def add(self, data, camera):
        if not isinstance(camera, str) or not camera.strip():
            raise ValueError('카메라 보관함 이름을 입력하세요.')
        source = data.get('_source', {})
        if source.get('payload_hex'):
            if hashlib.sha256(bytes.fromhex(source['payload_hex'])).hexdigest() != source.get('sha256'):
                raise ValueError('가져온 원본의 해시가 맞지 않습니다.')
        namespace = hashlib.sha256(camera.encode('utf-8')).hexdigest()
        target = self.root / namespace
        existing = self.entries()
        results = []
        for roll in data['rolls']:
            content = {'camera': camera, 'mode': data['mode'], 'roll': roll}
            key = hashlib.sha256(canonical(content)).hexdigest()
            path = target / (key + '.json')
            if path.exists():
                results.append({'status': 'duplicate', 'path': str(path)})
                continue
            previous = [x for x in existing if x['camera'] == camera and x['roll']['roll_number'] == roll['roll_number']]
            previous.sort(key=lambda x: x['imported'])
            relation = 'new'
            parent = None
            if previous:
                old = previous[-1]
                frames = old['roll']['frames']
                # Keep every version, including frame-identical ISO changes and shorter rereads.
                if old['mode'] == data['mode'] and len(roll['frames']) > len(frames) and roll['frames'][:len(frames)] == frames:
                    relation = 'prefix_growth'
                    parent = old['id']
                else:
                    relation = 'same_number_distinct'
            value = dict(content, id=key, imported=datetime.now(timezone.utc).isoformat(),
                         source=source, relation=relation, parent=parent)
            target.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            existing.append(value)
            results.append({'status': relation, 'path': str(path)})
        return results
