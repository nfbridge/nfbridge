# SPDX-License-Identifier: GPL-3.0-only
"""Roll-log Markdown and unmapped ExifTool CSV. Never write image metadata."""
import csv
from datetime import datetime
from fractions import Fraction
import json
from pathlib import Path
import re
import shutil
import roll_templates


def cell(value):
    return str(value or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('|','&#124;').replace('\r',' ').replace('\n','<br>').replace('`','&#96;')


def scalar(value):return json.dumps(value,ensure_ascii=False)


def number(value):
    try:
        text=str(value).strip()
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d+)?|\d+/\d+)',text):return ''
        return text if float(Fraction(text))>=0 else ''
    except (ValueError,ZeroDivisionError):return ''


def exposure(value):
    text=str(value).strip()
    return number(text[:-1] if text.endswith('"') else text)


def lens(frame):
    names=('lens_shortest_focal','lens_longest_focal','max_aperture_short','max_aperture_long')
    values=[number(frame.get(k,'')) for k in names]
    if not all(values):return None
    lo,hi,a,b=values
    focal=lo if lo==hi else lo+'-'+hi
    aperture=a if a==b else a+'-'+b
    return focal+'mm f/'+aperture, ' '.join(values)


def flash(frame, language='ko'):
    name=frame.get('flash_type')
    text={'off':'Off' if language=='en' else '없음','non_ttl':'Non-TTL','ttl':'TTL'}.get(name,name or '-')
    sync_suffix={
        'slow':(' Slow sync' if language=='en' else ' 슬로우 동조'),
        'rear':(' Rear curtain' if language=='en' else ' 후막'),
        'red_eye':(' Red-eye reduction' if language=='en' else ' 적목감소'),
        'red_eye_slow':(' Red-eye reduction + slow sync' if language=='en' else ' 적목감소+슬로우'),
    }.get(frame.get('flash_sync'))
    if sync_suffix:text+=sync_suffix
    comp=frame.get('flash_comp')
    if comp and comp not in ('0','0.0','+0.0'):text+=' '+str(comp)+' EV'
    if frame.get('multiple_exposure'):text+=' · Multiple exposure' if language=='en' else ' · 다중노출'
    return text


def roll_metadata(roll, supplied, imported):
    supplied=dict(supplied or {})
    date=supplied.get('date','')
    if date:datetime.strptime(date,'%Y-%m-%d')
    roll_id=supplied.get('roll_id','')
    if not roll_id and supplied.get('order') and supplied.get('film_code'):
        roll_id=(date.replace('-','')[2:] if date else imported.strftime('%y%m%d'))+'_F100_'+str(supplied['order'])+'_'+str(supplied['film_code'])
    roll_id=roll_id or 'F100_roll'+str(roll['roll_number'])
    if not re.fullmatch(r'[\w .-]{1,120}',roll_id,re.UNICODE) or roll_id in ('.','..'):
        raise ValueError('롤 이름에는 글자·숫자·공백·밑줄·하이픈만 사용하세요.')
    return dict(supplied,roll_id=roll_id,date=date or imported.strftime('%Y-%m-%d'),date_source='user' if date else 'imported')


WORDS_EN = {
    '필름 / 롤 마지막 감도':'Film / last recorded ISO',
    '항목':'Field','내용':'Value','바디 / 렌즈':'Camera / lens','필름 / EI':'Film / EI',
    '현상 / 현상소':'Process / lab','스캔':'Scan','기본 / 자가스캔 후보':'Lab scan / home scan candidate',
    '기간':'Dates','목적':'Purpose','촬영 중 메모':'Shooting notes','스캔 후 리뷰':'Review after scanning',
    '강한 컷 3:':'Three strongest frames:','보류 / 기록:':'Keep / revisit:',
    '기술 메모:':'Technical notes:','롤 회고:':'Roll reflection:','다음에 바꿀 한 가지:':'One change for next time:',
    '프레임 로그 (카메라 기록)':'Frame log (camera records)','피사체':'Subject','셔터':'Shutter',
    '조리개':'Aperture','초점':'Focal length','모드':'Mode','측광':'Metering','보정':'Compensation',
    '플래시':'Flash','판단/의도':'Decision / intent','결과 메모':'Result notes','컷':'Frame','렌즈':'Lens',
}


def markdown(roll, mode, meta, imported, sections=False, language='ko', template=None):
    if language not in ('ko','en'):raise ValueError('Unsupported export language')
    t=lambda key: WORDS_EN.get(key,key) if language=='en' else key
    frames=roll['frames'];lenses=list(dict.fromkeys(lens(f)[0] for f in frames if lens(f)))
    iso=roll.get('film_speed',roll.get('film_speed_raw',''))
    values={'type':'roll-log','date':meta['date'],'roll_id':meta['roll_id'],'camera':'Nikon F100',
        'film':meta.get('film',''),'rating_ei':int(iso) if str(iso).isdigit() else iso,
        'process':meta.get('process',''),'lab':meta.get('lab',''),'lenses':lenses,'frames':len(frames),
        'status':'imported','tags':['f100']+(['imported'] if meta['date_source']=='imported' else []),
        'f100_roll_no':roll['roll_number'],'f100_record_mode':mode,'f100_imported':imported.isoformat(timespec='seconds'),
        'f100_date_source':meta['date_source'], 'f100_iso_source':'last_exposed_frame'}
    frontmatter='\n'.join(['---']+[key+': '+scalar(value) for key,value in values.items()]+['---'])
    note = ('rating_ei is the last exposed frame ISO, not confirmed for every frame. Roll completion is unknown. '
            'Multiple-exposure values describe the first exposure only; completed exposure count is unknown.' if language=='en' else
            'rating_ei는 마지막 노출 컷의 감도이며 전 컷의 감도는 확인되지 않았습니다. 롤 촬영 완료 여부는 미확인입니다. '
            '다중노출 값은 첫 노출 기준이며 실제 완료 횟수는 알 수 없습니다.')
    frontmatter += '\n<!-- '+note+' -->'
    headers=['#','피사체','셔터','조리개','초점','모드','측광','보정','플래시','판단/의도','결과 메모']
    table=['| '+' | '.join(t(h) for h in headers)+' |','|'+'---|'*len(headers)]
    sections_out=[]
    for f in frames:
        meters={'matrix':'Matrix','spot':'Spot','center_weighted':'Center-weighted'} if language=='en' else {'matrix':'매트릭스','spot':'스팟','center_weighted':'중앙중점'}
        meter=meters.get(f.get('meter_mode'),f.get('meter_mode','-'))
        row=[f['frame_number'],'',f.get('shutter_speed','-'),f.get('aperture','-'),f.get('focal_length','-'),f.get('exposure_mode','-'),meter,f.get('exposure_comp','-'),flash(f,language),'','']
        table.append('| '+' | '.join(cell(v) if v!=0 else '0' for v in row)+' |')
        sections_out+=['','### '+t('컷')+' '+str(f['frame_number']),'',
                      '- '+t('렌즈')+': '+cell(lens(f)[0] if lens(f) else ''),
                      '- '+t('모드')+': '+cell(f.get('exposure_mode','-')),
                      '- '+t('셔터')+': '+cell(f.get('shutter_speed','-')),
                      '- '+t('조리개')+': '+cell(f.get('aperture','-')),
                      '- '+t('피사체')+': ','- '+t('판단/의도')+': ','- '+t('결과 메모')+': ']
    if template is not None:
        context={'frontmatter':frontmatter,'frames_table':'\n'.join(table),'frame_sections':'\n'.join(sections_out),
                 'roll_id':cell(meta['roll_id']),'roll_id_yaml':scalar(meta['roll_id']),
                 'camera':'Nikon F100','film':cell(meta.get('film','')),'film_yaml':scalar(meta.get('film','')),
                 'iso':cell(iso),'process':cell(meta.get('process','')),'lab':cell(meta.get('lab','')),
                 'lenses':cell(', '.join(lenses)),'frame_count':len(frames),'roll_number':roll['roll_number'],
                 'record_mode':mode,'date':meta['date'],'date_source':meta['date_source'],
                 'shooting_date':meta['date'] if meta['date_source']=='user' else '',
                 'imported':imported.isoformat(timespec='seconds')}
        return roll_templates.render(template,context)
    basic=[('roll_id',meta['roll_id']),('바디 / 렌즈','Nikon F100 / '+', '.join(lenses)),
           ('필름 / 롤 마지막 감도',str(meta.get('film',''))+' / '+str(iso)),
           ('현상 / 현상소',meta.get('process','')+' / '+meta.get('lab','')),
           ('스캔',t('기본 / 자가스캔 후보')),('기간',meta['date'] if meta['date_source']=='user' else '')]
    out=[frontmatter,'','# 📷 Roll Log — '+cell(meta['roll_id']),'','## Basic','',
         '| '+t('항목')+' | '+t('내용')+' |','|---|---|']
    out += ['| '+t(key)+' | '+cell(value)+' |' for key,value in basic]
    out += ['', '## '+t('목적'),'','- ','','## '+t('촬영 중 메모'),'','- ',
            '','## '+t('스캔 후 리뷰'),'',t('강한 컷 3:'),'- 1:','- 2:','- 3:','',
            t('보류 / 기록:'),'- ','',t('기술 메모:'),'- ','',t('롤 회고:'),'- ','',t('다음에 바꿀 한 가지:'),'- ',
            '','## '+t('프레임 로그 (카메라 기록)'),'',*table]
    if sections:out+=sections_out
    return '\n'.join(out)+'\n'


EXIF_COLUMNS=['SourceFile','ExposureTime','FNumber','FocalLength','ISO','ExposureCompensation','ExposureProgram#','MeteringMode#','Flash#','LensInfo','Make','Model','XMP-aux:FlashCompensation','DateTimeOriginal']


def exif_row(roll,frame,meta):
    # No date-only midnight, import-time date, Bulb duration, or unknown numeric values.
    timestamp=meta.get('datetime_original','')
    if timestamp:
        timestamp=datetime.strptime(timestamp,'%Y-%m-%d %H:%M:%S').strftime('%Y:%m:%d %H:%M:%S')
    def comp(key):
        v=str(frame.get(key,''))
        return v if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',v) else ''
    iso = number(roll.get('film_speed','')) if meta.get('iso_unchanged_confirmed') is True else ''
    return ['',exposure(frame.get('shutter_speed','')),number(frame.get('aperture','')),number(frame.get('focal_length','')),iso,
        comp('exposure_comp'),{'M':1,'P':2,'A':3,'S':4}.get(frame.get('exposure_mode'),''),
        {'matrix':5,'spot':3,'center_weighted':2}.get(frame.get('meter_mode'),''),
        0 if frame.get('flash_type')=='off' else '',lens(frame)[1] if lens(frame) else '', 'NIKON','F100',comp('flash_comp'),timestamp]


def save(data,directory,metadata=None,imported=None,sections=False,vault=None,language="ko",template=None,formats=None):
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
    directory=Path(directory);imported=imported or datetime.now().astimezone();metadata=metadata or {}
    if language not in ('ko','en'):raise ValueError('Unsupported export language')
    if template is not None:roll_templates.validate(template)
    pages=[];exif=[];mapping=[];used=set()
    for roll in data.get('rolls',[]):
        meta=roll_metadata(roll,metadata.get(str(roll['roll_number']),{}),imported)
        filename=meta['roll_id']+'.md'
        if filename.casefold() in used:raise ValueError('서로 다른 롤의 파일 이름이 같습니다.')
        used.add(filename.casefold())
        path=directory/filename
        if 'markdown' in formats:
            with path.open('x',encoding='utf-8') as f:f.write(markdown(roll,data['mode'],meta,imported,sections,language,template))
        if 'markdown' in formats:
            pages.append(path)
        for frame in roll['frames']:
            exif.append(exif_row(roll,frame,meta));mapping.append({'csv_row':len(exif)+1,'roll':roll['roll_number'],'frame':frame['frame_number'],'roll_id':meta['roll_id']})
    if 'exif' in formats:
      with (directory/'exiftool.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(EXIF_COLUMNS);writer.writerows(exif)
      (directory/'exiftool-row-map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+'\n')
    note_en = ('SourceFile is blank. Use exiftool-row-map.json to match roll/frame numbers to actual scan files before using this CSV. It is not ready to execute as-is.\n'
               'ISO is omitted unless the user confirms unchanged sensitivity for this roll. The camera retains only the last exposed frame ISO.\n'
               'Multiple-exposure values describe the first exposure only; completed exposure count is unknown.\n'
               'The camera does not record capture time. Date-only input leaves DateTimeOriginal blank.\n'
               'TTL flags are not EXIF Flash bits; Bulb duration is also left blank.\n'
               'Exporting this CSV does not modify images. The app has a separate, confirmed scan-writing action.\n')
    note_ko = ('SourceFile은 비어 있습니다. exiftool-row-map.json의 롤·컷 번호를 보고 실제 스캔 파일과 대응시킨 뒤 사용하세요. 아직 실행 가능한 완성 CSV가 아닙니다.\n'
               'ISO는 이 롤의 감도를 바꾸지 않았다고 사용자가 확인한 경우에만 포함합니다. 카메라는 마지막 노출 컷의 감도만 보존합니다.\n'
               '다중노출 값은 첫 노출 기준이며 실제 완료 횟수는 알 수 없습니다.\n'
               '카메라는 촬영시각을 기록하지 않습니다. 날짜만 입력한 경우 DateTimeOriginal도 비웁니다.\n'
               'TTL 플래그는 EXIF Flash 비트와 동일하지 않아 자동 변환하지 않습니다. BULB의 실제 지속시간도 비웁니다.\n'
               '이 CSV를 내보내는 것만으로 사진을 수정하지 않습니다. 앱의 스캔 쓰기는 별도 확인을 거칩니다.\n')
    if 'exif' in formats:
        (directory/'EXIF_README.txt').write_text((note_en if language=='en' else note_ko)+'https://exiftool.org/exiftool_pod2.html\nhttps://exiftool.org/TagNames/XMP.html#aux\n',encoding='utf-8')

    copies=[]
    if vault:
        destination=Path(vault).expanduser().resolve(strict=True)
        if not destination.is_dir():raise ValueError('볼트 폴더가 아닙니다.')
        for path in pages:
            target=destination/path.name
            # Never replace an existing user's annotated roll log.
            if target.exists() or target.is_symlink():
                copies.append({'file':str(target),'status':'existing_not_overwritten'});continue
            with path.open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
            copies.append({'file':str(target),'status':'copied'})
    return {'markdown':[p.name for p in pages],'vault':copies,'language':language,'template':'custom' if template is not None else 'builtin'}
