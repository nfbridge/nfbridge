# SPDX-License-Identifier: GPL-3.0-only
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import exports
import nfbridge
import report
import roll_templates
from i18n import Translator

WHEN = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


class DocumentTemplates(unittest.TestCase):
    def test_english_outputs_preserve_machine_data_and_user_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = nfbridge.demo_data()
            meta = {'1': {'film': '내 필름 <test> | review'}}
            for language in ('ko', 'en'):
                report.save(data, root/language, language=language, metadata=meta, imported=WHEN, demo=True)
            en = root/'en'; ko = root/'ko'
            self.assertEqual((en/'shooting-data.json').read_bytes(), (ko/'shooting-data.json').read_bytes())
            self.assertEqual((en/'exiftool.csv').read_bytes(), (ko/'exiftool.csv').read_bytes())
            note = (en/'F100_roll1.md').read_text()
            self.assertIn('## Purpose', note)
            self.assertIn('## Frame log (camera records)', note)
            self.assertIn('Multiple exposure', note)
            self.assertIn('내 필름 <test> | review', note)  # YAML string, not translated
            self.assertIn('내 필름 &lt;test&gt; &#124; review', note)
            self.assertEqual(note.split('---')[1], (ko/'F100_roll1.md').read_text().split('---')[1])
            html = (en/'index.html').read_text()
            self.assertIn('lang="en"', html)
            self.assertIn('<th>Shutter</th>', html)
            self.assertIn('Synthetic demo', html)
            with (en/'shooting-data.csv').open(encoding='utf-8-sig') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['Shutter'], '1/400')
            self.assertEqual(rows[0]['Metering'], 'Matrix')
            self.assertEqual(rows[2]['Multiple exposure'], 'Yes')

    def test_custom_layout_only_substitutes_known_placeholders_once(self):
        roll = nfbridge.demo_data()['rolls'][0]
        meta = exports.roll_metadata(roll, {'film': '{{iso}}\nA: "B"'}, WHEN)
        template = '{{frontmatter}}\n# My headings\n{{film}}\nfilm: {{film_yaml}}\n{{frames_table}}\n## Notes\n- '
        text = exports.markdown(roll, 'detailed', meta, WHEN, language='en', template=template)
        self.assertIn('# My headings', text)
        self.assertIn('{{iso}}<br>A: "B"', text)
        self.assertIn('film: "{{iso}}\\nA: \\"B\\""'.replace('\\\\','\\'), text)
        self.assertIn('| # | Subject | Shutter |', text)
        self.assertTrue(text.endswith('## Notes\n- '))

    def test_template_never_evaluates_code_or_accepts_unknown_fields(self):
        for text in ['{{__import__("os").system("echo BAD")}}', '{{frame.__class__}}', '{{unknown}}', '{{roll_id}', '{{roll_id}} }}']:
            with self.assertRaises(ValueError):
                roll_templates.render(text, {})
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'not-created'
            with self.assertRaises(ValueError):
                report.save(nfbridge.demo_data(), target, template='{{invalid}}')
            self.assertFalse(target.exists())

    def test_empty_simple_fields_and_explicit_dates(self):
        roll = {'roll_number': 44, 'frames': [{'frame_number': 1, 'flash_type': 'off'}], 'film_speed': '400'}
        meta = exports.roll_metadata(roll, {}, WHEN)
        text = exports.markdown(roll, 'simple', meta, WHEN, language='en', template='{{shooting_date}}\n{{date_source}}\n{{frames_table}}')
        self.assertTrue(text.startswith('\nimported\n'))
        self.assertIn('| 1 |  | - | - | - | - | - | - | Off |', text)

    def test_template_read_limit_and_private_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mine.md'
            path.write_text(roll_templates.SAMPLE, encoding='utf-8-sig')
            self.assertEqual(roll_templates.read_template(path), roll_templates.SAMPLE)
            settings = Translator(folder)
            settings.update_preferences({'document_template_path': str(path), 'export_language': 'en'})
            settings.set_language('ko')
            self.assertEqual(settings.preferences()['document_template_path'], str(path))
            self.assertEqual(settings.preferences()['export_language'], 'en')
            path.write_bytes(b'a' * (roll_templates.MAX_TEMPLATE_BYTES+1))
            with self.assertRaises(ValueError):
                roll_templates.read_template(path)

    def test_bilingual_blank_sample_contains_no_personal_values(self):
        roll = nfbridge.demo_data()['rolls'][0]
        meta = exports.roll_metadata(roll, {}, WHEN)
        for language in ('ko', 'en'):
            text = exports.markdown(roll, 'detailed', meta, WHEN, language=language,
                                    template=roll_templates.sample(language))
            self.assertNotIn('{{', text)
            self.assertIn('type: "roll-log"', text)
            self.assertIn('f100_roll_no: 1', text)
            self.assertIn('## 스캔 후 리뷰' if language == 'ko' else '## Review after scanning', text)
            self.assertIn('- 1:\n- 2:\n- 3:', text)

    def test_default_english_template_contains_only_allowlisted_fields(self):
        roll = nfbridge.demo_data()['rolls'][0]
        meta = exports.roll_metadata(roll, {}, WHEN)
        text = exports.markdown(roll, 'detailed', meta, WHEN, language='en', template=roll_templates.SAMPLE)
        self.assertNotIn('{{', text)
        self.assertIn('## My notes', text)
        self.assertIn('1/400', text)


if __name__ == '__main__':
    unittest.main()
