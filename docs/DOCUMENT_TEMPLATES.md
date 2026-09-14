# Document languages and personal templates

[한국어](DOCUMENT_TEMPLATES.ko.md)

Choose **Document template** below the roll list. Select **Follow interface language**, **Korean**, or **English**. HTML, readable CSV, the built-in roll log and export instructions use that language. JSON field names and ExifTool CSV tags remain stable so other software can read them. Your film names and notes are never translated.

To use your own Markdown layout:

1. Choose **Save sample template** and open the saved `.md` file in a text or Markdown editor.
2. Keep your headings and blank note fields. Move the placeholders wherever you want.
3. Choose **Personal Markdown template → Choose template file**. Use **Preview**, then **Apply**.
4. Choose Markdown roll logs in **Save** to use that template for the `.md` file. It does not change the layout of HTML or the machine-readable files.

Minimal example:

```markdown
{{frontmatter}}

# {{roll_id}}

Film: {{film}} · EI: {{iso}}

## My notes

- Subject:
- Intention:
- Review:

{{frames_table}}
```

`{{frontmatter}}` adds the complete YAML block, including its `---` delimiters. `{{frames_table}}` adds the frame table in the selected document language; `{{frame_sections}}` adds one section per frame. Your custom headings stay exactly as written in the template.

Other placeholders: `roll_id`, `camera`, `film`, `iso`, `process`, `lab`, `lenses`, `frame_count`, `roll_number`, `record_mode`, `date`, `date_source`, `shooting_date`, `imported`, `film_yaml`, `roll_id_yaml`. Enclose a name in double braces. For a custom YAML field, use the `_yaml` variant without extra quotes; normal text values are escaped for Markdown. The complete `frontmatter` block is the simplest option.

`shooting_date` is blank unless supplied explicitly. `date` follows the existing roll-log convention: supplied date or import date, identified by `date_source`. The F100 does not supply a capture date. Unavailable Simple-mode fields remain `-`; personal observations stay blank.

Templates are UTF-8 Markdown up to 256 KB. Only these placeholders are supported: there are no executable expressions, loops, file includes, shell commands or Python. Unknown/malformed placeholders produce an error before creating export files. Inserted data is not processed again as a template.

The app remembers the chosen path in its local preferences. The template is not copied into the application or public package. Changes to the file are read on the next preview/export. Existing exported files and vault notes are not overwritten; use a new output folder. Changing a layout is document editing, not application development. Arbitrary Word/HTML layouts and custom frame-column definitions are outside this version.

The sample is a blank roll-log layout shared with permission: Basic, Purpose, Shooting notes, Review after scanning, and Frames. It contains no personal photographs, roll records, or notes. Save a sample in the selected output language, edit its headings or blank sections, and select it as your personal template. No application code changes are needed.
