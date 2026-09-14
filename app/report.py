# SPDX-License-Identifier: GPL-3.0-only
"""Local, self-contained shooting-data reports. No external resources."""
import csv
import html
import io
import json
from pathlib import Path
from urllib.parse import quote
import exports

COLUMNS = [('roll','롤'),('iso','롤 마지막 감도'),('frame','컷'),('shutter','셔터'),('aperture','조리개'),('focal','초점거리'),('mode','모드'),('meter','측광'),('comp','노출보정'),('flash_comp','플래시보정'),('flash','플래시'),('sync','플래시 발광 시점'),('multiple','다중노출')]

EN_COLUMNS = dict(roll='Roll',iso='Last recorded ISO',frame='Frame',shutter='Shutter',aperture='Aperture',focal='Focal length',mode='Mode',meter='Metering',comp='Exposure compensation',flash_comp='Flash compensation',flash='Flash',sync='Flash timing',multiple='Multiple exposure')


def rows(data, language="ko"):
    for roll in data.get('rolls', []):
        for frame in roll.get('frames', []):
            yield dict(roll=roll['roll_number'], iso=roll.get('film_speed', roll.get('film_speed_raw','—')),
                       frame=frame['frame_number'], shutter=frame.get('shutter_speed','—'),
                       aperture=frame.get('aperture','—'), focal=frame.get('focal_length','—'),
                       mode=frame.get('exposure_mode','—'), meter=({'matrix':'Matrix','spot':'Spot','center_weighted':'Center-weighted'} if language=='en' else {'matrix':'멀티','spot':'스팟','center_weighted':'중앙중점'}).get(frame.get('meter_mode'),frame.get('meter_mode','—')),
                       comp=frame.get('exposure_comp','—'), flash_comp=frame.get('flash_comp','—'),
                       flash=({'off':'Off','ttl':'TTL'} if language=='en' else {'off':'없음','ttl':'TTL'}).get(frame.get('flash_type'),frame.get('flash_type','—')),
                       sync=({'normal':'Normal (front curtain)','rear':'Rear curtain'} if language=='en' else {'normal':'일반(선막)','rear':'후막'}).get(frame.get('flash_sync'),frame.get('flash_sync','—')),
                       multiple=('Yes' if frame.get('multiple_exposure') else 'No') if language=='en' else ('예' if frame.get('multiple_exposure') else '아니오'))


def csv_cell(value):
    # Prevent spreadsheet formula execution for text imported from external JSON.
    text = str(value)
    if text.lstrip().startswith(('=', '@', '+', '-')):
        try:
            float(text)
        except ValueError:
            return "'" + text
    return text


def save(data, directory, *, demo=False, metadata=None, imported=None, sections=False, vault=None, language="ko", template=None, formats=None):
    default_formats = {'html', 'markdown', 'json', 'csv', 'exif'}
    if formats is None:
        formats = default_formats
    else:
        formats = set(formats)
        if not formats:
            raise ValueError('파일 형식을 하나 이상 선택하세요.')
        unknown = formats - default_formats
        if unknown:
            raise ValueError('지원하지 않는 저장 형식입니다: ' + ', '.join(sorted(unknown)))
    if language not in ('ko','en'):raise ValueError('Unsupported export language')
    if template is not None:exports.roll_templates.validate(template)
    en = language == 'en'
    t = lambda ko, english: english if en else ko
    columns = [(key, EN_COLUMNS[key] if en else label) for key,label in COLUMNS]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if 'json' in formats:
        (directory/'shooting-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    extra_outputs=exports.save(data,directory,metadata=metadata,imported=imported,sections=sections,vault=vault,language=language,template=template, formats=formats)
    # Keep export bookkeeping hidden from the user's five selectable files.
    (directory/'.nfbridge-export-status.json').write_text(json.dumps(extra_outputs,ensure_ascii=False,indent=2)+'\n')
    records=list(rows(data,language))
    if 'csv' in formats:
      with (directory/'shooting-data.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow([label for _,label in columns]+[t('전체 원시·해석 필드 JSON','All raw and decoded fields (JSON)')])
        frames=[f for r in data.get('rolls',[]) for f in r['frames']]
        writer.writerows([[csv_cell(row[key]) for key,_ in columns]+[json.dumps(frame,ensure_ascii=False)] for row,frame in zip(records,frames)])
    esc=lambda x:html.escape(str(x),quote=True)
    options=''.join('<option value="'+esc(r['roll_number'])+'">'+t('롤','Roll')+' '+esc(r['roll_number'])+t(' · 마지막 ISO ',' · Last ISO ')+esc(r.get('film_speed','—'))+'</option>' for r in data.get('rolls',[]))
    titles = {
        'iso': t('감도는 마지막 노출 컷 기준입니다.', 'ISO is from the last exposed frame.'),
        'multiple': t('다중노출은 첫 노출 값만 표시합니다.', 'Multiple exposure shows the first exposure only.'),
        'sync': t('일반은 선막, 후막은 셔터가 닫히기 직전 발광입니다.', 'Normal is front curtain; rear is just before the shutter closes.'),
    }
    headings=''.join('<th'+((' title="'+esc(titles[key])+'"') if key in titles else '')+'>'+esc(label)+'</th>' for key,label in columns)
    body=''.join('<tr data-roll="'+esc(row['roll'])+'">'+''.join('<td>'+esc(row[key])+'</td>' for key,_ in columns)+'</tr>' for row in records)
    label=t('예제 데이터 · 카메라를 읽지 않았습니다','Synthetic demo · no camera was read') if demo else t('가져온 촬영정보','Imported shooting records')
    title=t('촬영정보','Shooting records')
    summary=str(data.get('roll_count',0))+t('롤 · ',' rolls · ')+str(len(records))+t('컷',' frames')+' · Nikon F100'
    link_items=[]
    if 'csv' in formats: link_items.append('<a href="shooting-data.csv" download>'+t('CSV 저장','Save CSV')+'</a>')
    if 'json' in formats: link_items.append('<a href="shooting-data.json" download>'+t('원본 데이터 저장','Save original data')+'</a>')
    if 'exif' in formats: link_items.append('<a href="exiftool.csv" download>'+t('EXIF 작업용 CSV','EXIF working CSV')+'</a>')
    link_items += ['<a href="'+quote(name)+'" download>'+esc(name)+'</a>' for name in extra_outputs['markdown']]
    links=''.join(link_items)
    footer=t('F--는 조리개 정보 없음입니다.','F-- means aperture information is unavailable.')
    if 'json' in formats:
        footer += ' ' + t('원본 데이터 보관 파일에서 원시값과 해석값을 함께 확인할 수 있습니다.', 'The original-data file keeps raw and interpreted values together.')
    local=t('이 보고서는 컴퓨터 안에서 열립니다. 외부 서버에 촬영정보를 전송하지 않습니다.','This report opens locally. No shooting data is sent to an external server.')
    css = 'body{font:16px -apple-system,BlinkMacSystemFont,sans-serif;background:#f7f5f0;color:#202c29;margin:0;padding:36px}main{max-width:1400px;margin:auto}h1{font-size:32px;margin-bottom:8px}.muted{color:#596963}nav{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}a,select{padding:10px 14px;border:1px solid #bac8c0;border-radius:8px;background:white;color:#174b39;text-decoration:none;font:inherit}.scroll{overflow:auto;border:1px solid #d5ddd6;border-radius:10px;background:white}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid #e6ebe6}th{background:#e9efe8;position:sticky;top:0}tr:hover{background:#f2f6f1}.tag{display:inline-block;background:#e5eddb;padding:7px 12px;border-radius:20px}footer{margin-top:24px;font-size:14px;line-height:1.7}'
    page=(f'<!doctype html><html lang="{language}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>Neo Film Bridge — {title}</title><style>{css}</style><main><span class="tag">{esc(label)}</span>'
          f'<h1>Neo Film Bridge</h1><p class="muted">{summary}</p><nav><select id="roll" aria-label="'+t('롤 선택','Select roll')+'"><option value="">'+t('모든 롤','All rolls')+'</option>'+options+'</select>'
          +links+'</nav>'
          '<div class="scroll"><table><thead><tr>'+headings+'</tr></thead><tbody>'+body+'</tbody></table></div><footer class="muted">'+footer+'<br>'+local+'</footer></main>'
          "<script>document.getElementById('roll').addEventListener('change',function(){document.querySelectorAll('tbody tr').forEach(r=>r.hidden=this.value!==''&&r.dataset.roll!==this.value);});</script></html>")
    if 'html' in formats:
        (directory/'index.html').write_text(page,encoding='utf-8')
    if 'html' in formats:
        return directory/'index.html'
    for name in ('markdown','csv','json','exif'):
        if name == 'markdown' and extra_outputs['markdown']:
            return directory/extra_outputs['markdown'][0]
        candidate = {'csv':'shooting-data.csv','json':'shooting-data.json','exif':'exiftool.csv'}.get(name)
        if candidate and candidate in {p.name for p in directory.iterdir()}:
            return directory/candidate
    return directory
