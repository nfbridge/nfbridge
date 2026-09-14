# SPDX-License-Identifier: GPL-3.0-only
import ast
import json
from pathlib import Path
import string
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from i18n import EN, GENERIC_ERROR, Translator


class Languages(unittest.TestCase):
    def test_switch_persists_without_losing_other_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            path.write_text(json.dumps({'last_export': '/example/folder'}))
            t = Translator(folder)
            self.assertEqual(t.text('기록 설정'), '기록 설정')
            t.set_language('en')
            self.assertEqual(Translator(folder).text('기록 설정'), 'Recording settings')
            self.assertEqual(json.loads(path.read_text())['last_export'], '/example/folder')
            t.set_language('ko')
            self.assertEqual(Translator(folder).language, 'ko')

    def test_bad_preferences_use_korean_and_invalid_language_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preferences.json'
            for value in ['{broken', '[]', '{"language":"unknown"}']:
                path.write_text(value)
                t = Translator(folder)
                self.assertEqual(t.language, 'ko')
                with self.assertRaises(ValueError):
                    t.set_language('fr')
                self.assertEqual(path.read_text(), value)

    def test_translation_placeholders_are_identical(self):
        formatter = string.Formatter()
        for ko, en in EN.items():
            fields = lambda text: {name for _, name, _, _ in formatter.parse(text) if name is not None}
            self.assertEqual(fields(ko), fields(en), ko)
            self.assertTrue(en.strip())

    def test_gui_and_backend_korean_strings_have_translations(self):
        for name in ('gui.py', 'scans.py', 'library.py', 'camera.py'):
            tree = ast.parse((ROOT / 'app' / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if any('\uac00' <= c <= '\ud7a3' for c in node.value) and node.value != '한국어':
                        self.assertIn(node.value, EN, (name, node.lineno, node.value))

    def test_errors_and_dynamic_results_keep_user_data_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            t = Translator(folder)
            t.set_language('en')
            filename = '사용자 {사진}.tif_original'
            message = '이전에 남겨둔 수정 전 사진이 있습니다. 기존 폴더는 보관하고, 작업할 JPEG/TIFF만 새 폴더로 복사해 선택하세요: ' + filename
            self.assertTrue(t.error(message).endswith(filename))
            self.assertEqual(t.error('Traceback internal secret'), EN[GENERIC_ERROR])
            key = '{ok}/{total}개 검증 완료 · 결과 기록: {path}'
            self.assertIn(filename, t.text(key, ok=2, total=3, path=filename))


if __name__ == '__main__':
    unittest.main()
