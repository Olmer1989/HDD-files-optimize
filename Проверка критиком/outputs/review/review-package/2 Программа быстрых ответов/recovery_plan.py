"""Read-only planning for a recovered directory using the shared hashbase.

Expected hashes come from the original inventory. They are NOT hashes of the
recovered bytes. Never inserts unverified recovery results as trusted copies.
"""
import collections
import csv
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time

RAW=set('.raw .cr2 .cr3 .nef .nrw .dng .arw .srf .sr2 .orf .rw2 .raf .pef'.split())
PHOTO=RAW|set('.jpg .jpeg .heic .heif .png .tif .tiff .webp .bmp .gif .avif'.split())
VIDEO=set('.avi .mpg .mpeg .m2p .m2t .m2v .dv .mov .mp4 .mkv .m4v .mts .m2ts .wmv .vob .flv .3gp .mod .tod .mxf .ts .webm'.split())
DIGITAL={'.avi','.mpg','.mpeg','.m2p','.dv'}
SYSTEM={'windows','program files','program files (x86)','programdata','boot','msocache','intel','amd','config.msi',
        'system volume information','$windows.~bt','recycler','$recycle.bin','found.000','found.001'}
CACHE=re.compile(r'googlemv|webmapcache|media cache|encoded files|premiere pro previews|render cache|cacheclip|\\temp(\\|$)|\\thumbs\.db$',re.I)
SAFARI=re.compile(r'сафари|safari|портал|летопись|(?<!\w)ан(?!\w)|анабар|котуйкан|мойеро|котуй|котуя|кочечум|олен[её]к|хатанга|путорано',re.I)
FAMILY=re.compile(r'сашин|сашины|сашиного|зверев|танин|таня|наташ|соммелье',re.I)
TRAIN=re.compile(r'рафтинг|трениров|гребл|слалом',re.I)
TRAVEL=re.compile(r'алтай|рыбачий|сахалин|дагестан|архыз|домбай|путешеств',re.I)

def section(path,size,big_folders=()):
    p=PureWindowsPath(path);ext=p.suffix.lower();top=p.parts[0].casefold() if p.parts else ''
    if top in {'$recycle.bin','recycler','found.000','found.001'}:return 'Другое','удалённое/восстановленное: ручной разбор, не считать мусором автоматически'
    if top in SYSTEM or CACHE.search('\\'+path):return 'Другое','системное/кеш/корзина: кандидат на исключение, не удалять автоматически'
    if FAMILY.search(path):return 'Саша, Таня, Наташа','по названию папки; сохранить сопроводительные материалы'
    if SAFARI.search(path):return 'Сафари','по названию; RAW северных экспедиций относится сюда же'
    if top=='сайт рцнк':return 'Другое','рабочий сайт РЦНК: согласовать раздел, не считать автоматически семейными фото'
    if top=='туризм' and re.search(r'карты|картограф|навигац|gps',path,re.I):return 'Другое','карты/навигация: предложить хранение вместе с Сафари, требуется решение'
    if re.search(r'(^|\\)(фильмы(?: hd.*)?|фильмы blue.?ray|сборник фильмов[^\\]*|movies|films)(\\|$)',path,re.I):return 'Фильмы','по названию папки'
    if ext in VIDEO and (re.search(r'оцифров|кассет|vhs|minidv|denisvideos',path,re.I) or (ext in DIGITAL and str(p.parent) in big_folders)):
        return 'Оцифрованные источники','AVI/MPEG в папке с крупными оцифровками; включая короткие части'
    if TRAIN.search(path) or re.search(r'водный туризм',path,re.I):return 'Туризм, рафтинг','по названию; связь с событием сохранить'
    if top=='туризм':return 'Другое','папка с общим названием Туризм: уточнить, не считать автоматически рафтингом'
    if TRAVEL.search(path):return 'Путешествия','по названию события'
    if ext in RAW:return 'Фотки RAW + фото ТУРИЗМА 2021–2026','по формату; год/съёмка пока не подтверждены'
    if ext in PHOTO:return 'Фотки JPEG + фото 2021–2026','изображения вне тематических разделов; год не подтверждён'
    return 'Другое','требуется решение; документы/проекты не отделять от события'

def original_candidate(path,known):
    if path.casefold() in known:return path.casefold(),'точный путь'
    p=PureWindowsPath(path)
    name=re.sub(r'\.Id[^.]+(?=\.[^.]+$)','',p.name,flags=re.I)
    alt=str(p.with_name(name)).casefold()
    if alt!=path.casefold() and alt in known:return alt,'вариант имени R-Studio, содержимое не проверено'
    return None,'нет пути в описи'

def cmd_recovery_plan(a,hb):
    if getattr(a,'cached',False):return reclassify(a,hb)
    root=a.root.resolve()
    if not root.is_dir():raise ValueError('Нет восстановленной папки: '+str(root))
    c,jobs=hb.connect();hb.check_disk(c,a.disk)
    expected={p.casefold():(p,n,s) for p,n,s in c.execute('select path,size,sha from files where disk=?',(a.disk,))}
    presence={p.casefold():(g,s,n) for p,size,sha,g,s,n in hb.presence(c,a.disk,'')}
    big={str(PureWindowsPath(p).parent) for p,n,s in expected.values() if PureWindowsPath(p).suffix.lower() in DIGITAL and n>=7*2**30}
    decs=hb.decisions_for(a.disk)
    # Explicit user-waived Ecuador material, recorded for HDD61 in the journal.
    def waived(p):
        if a.disk!='HDD61' or not p.startswith('Монтаж Эквадора копия винчестера\\'):return False
        rel=p.split('\\',1)[1];first=rel.split('\\')[0]
        return first.startswith('Рабочие материалы') or first in {'Проекты Encore DVD','Проекты Adobe','Adobe Premiere Pro Auto-Save','Encoded Files','66e25584712a44c4cb204766686e49','e4095fead73aedc0b13d794dd4'} or PureWindowsPath(rel).name in {'Спринт.avi','Дорога Кито - Борха.avi','Верхнее поле - 8000.mpg','Деинтерл - 8000.mpg'}
    output=hb.ANSWERS/('разбор восстановления - '+a.disk);output.mkdir(parents=True,exist_ok=True)
    detail=output/'Файлы.tsv'
    sections=collections.defaultdict(lambda:collections.Counter());folders=collections.defaultdict(lambda:collections.Counter())
    errors=[];stack=[root];seen=set();count=0;last=time.monotonic();hashed_state=collections.Counter()
    with detail.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['Раздел (предварительно)','Путь восстановления','Размер, байт','Статус описи','Исходный путь','Ожидаемый SHA-256, не проверен','Есть на 45 по базе','Есть на 77 по базе','Других носителей по базе','Предложение','Основание'])
        while stack:
            directory=stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for e in entries:
                        name=e.name.casefold()
                        if name=='.env' or name.startswith('.env.') or name.endswith('.env'):continue
                        try:
                            st=e.stat(follow_symlinks=False)
                            if getattr(st,'st_file_attributes',0)&0x400 or stat.S_ISLNK(st.st_mode):continue
                            if stat.S_ISDIR(st.st_mode):stack.append(Path(e.path));continue
                            if not stat.S_ISREG(st.st_mode):continue
                            rel=str(Path(e.path).relative_to(root));key,match=original_candidate(rel,expected)
                            orig,n,sha=expected[key] if key else (rel,None,None)
                            good_size=n==st.st_size if key else False
                            g,s,nd=presence.get(key,(None,None,None))
                            sec,why=section(orig,st.st_size,big)
                            verdict=hb.decision_of(orig,decs)
                            if waived(orig):action='пользователь признал ненужным'
                            elif verdict:action='решение: '+verdict
                            elif not key or not good_size:action='разобрать: нет сопоставления или другой размер'
                            elif sha and g and s:action='кандидат на дубль: оригинал есть на 45 и 77; восстановленное содержимое не проверено'
                            elif sec=='Другое':action='ручное решение; не удалять значимые документы без копий'
                            elif sec in {'Сафари','Саша, Таня, Наташа','Фильмы','Оцифрованные источники'}:action='план: на тематический диск; сопоставление только по оглавлению'
                            else:action=('план: добавить на '+', '.join(t for t,v in [('45',g),('77',s)] if not v)+'; восстановленное содержимое не проверялось') if sha else 'нет хеша; сохранить с событием и разобрать'
                            state=match+('; размер совпал' if good_size else '; размер отличается' if key else '')
                            w.writerow([sec,rel,st.st_size,state,orig,sha or '',g if g is not None else '?',s if s is not None else '?',nd-1 if nd is not None else '?',action,why])
                            for agg in (sections[sec],folders[(sec,orig.split('\\')[0])]):
                                agg['files']+=1;agg['bytes']+=st.st_size
                                if key and good_size and sha:
                                    agg['matched_hashed']+=1
                                    if not g:agg['missing45_bytes']+=st.st_size
                                    if not s:agg['missing77_bytes']+=st.st_size
                                    if g and s:agg['both_bytes']+=st.st_size
                                elif not sha:agg['unhashed_bytes']+=st.st_size
                                if not key or not good_size:agg['review_bytes']+=st.st_size
                            count+=1
                            if key:seen.add(key)
                            hashed_state['matched_path_size_sha' if key and good_size and sha else 'matched_path_size_no_sha' if key and good_size else 'review']+=1
                            if time.monotonic()-last>10:print('Метаданные восстановления:',count,flush=True);last=time.monotonic()
                        except OSError as exc:errors.append((e.path,str(exc)))
            except OSError as exc:errors.append((str(directory),str(exc)))
    with (output/'Папки.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['Раздел','Папка','Файлов','ГиБ','Оригиналов нет45, ГиБ','Оригиналов нет77, ГиБ','Оригиналы есть на обоих, ГиБ','Без хеша, ГиБ','Разобрать сопоставление, ГиБ'])
        for (sec,folder),v in sorted(folders.items(),key=lambda kv:-kv[1]['bytes']):w.writerow([sec,folder,v['files'],round(v['bytes']/2**30,3),*[round(v[k]/2**30,3) for k in ['missing45_bytes','missing77_bytes','both_bytes','unhashed_bytes','review_bytes']]])
    result={'disk':a.disk,'root':str(root),'scope':'metadata only; expected SHA and copies are from the catalog, not verified recovery contents',
            'files':count,'matching':dict(hashed_state),'expected_paths_not_observed':len(expected.keys()-seen),
            'errors':errors,'sections':{k:dict(v) for k,v in sections.items()}}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));print('Подробности:',output)

def reclassify(a,hb):
    """Reapply draft rules to a saved directory listing; never accesses recovery drive."""
    output=hb.ANSWERS/('разбор восстановления - '+a.disk)
    source=output/'Файлы.tsv';temp=output/'Файлы.tmp.tsv'
    summary_path=output/'summary.json';summary=json.loads(summary_path.read_text(encoding='utf-8'))
    big=set()
    with source.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f,delimiter='\t'):
            p=PureWindowsPath(r['Исходный путь'])
            if p.suffix.lower() in DIGITAL and int(r['Размер, байт'])>=7*2**30:big.add(str(p.parent))
    sections=collections.defaultdict(collections.Counter);folders=collections.defaultdict(collections.Counter)
    other_classes=collections.defaultdict(collections.Counter)
    with source.open(encoding='utf-8-sig',newline='') as f,temp.open('w',encoding='utf-8-sig',newline='') as dest:
        reader=csv.DictReader(f,delimiter='\t');writer=csv.DictWriter(dest,fieldnames=reader.fieldnames,delimiter='\t');writer.writeheader()
        for r in reader:
            p=r['Исходный путь'];n=int(r['Размер, байт']);sha=r['Ожидаемый SHA-256, не проверен'];matched='размер совпал' in r['Статус описи']
            sec,why=section(p,n,big);r['Раздел (предварительно)']=sec;r['Основание']=why
            g=r['Есть на 45 по базе']=='1';s=r['Есть на 77 по базе']=='1'
            old=r['Предложение']
            if not old.startswith(('пользователь','решение:')):
                if not matched:r['Предложение']='разобрать: нет сопоставления или другой размер'
                elif sha and g and s:r['Предложение']='кандидат на дубль: оригинал есть на 45 и 77; восстановленное содержимое не проверено'
                elif sec=='Другое':r['Предложение']='ручное решение; документы и проекты сохранить до разбора'
                elif sec in {'Сафари','Саша, Таня, Наташа','Фильмы','Оцифрованные источники'}:r['Предложение']='план: на тематический диск; только сведения из описи и оглавления'
                else:r['Предложение']=('план: добавить на '+', '.join(t for t,v in [('45',g),('77',s)] if not v)+'; без пересчёта хешей') if sha else 'нет хеша; сохранить с событием и разобрать'
            writer.writerow(r)
            for v in [sections[sec],folders[(sec,p.split('\\')[0])]]:
                v['files']+=1;v['bytes']+=n
                if sha and matched:
                    v['matched_hashed']+=1
                    if not g:v['missing45_bytes']+=n
                    if not s:v['missing77_bytes']+=n
                    if g and s:v['both_bytes']+=n
                elif not sha:v['unhashed_bytes']+=n
                if not matched:v['review_bytes']+=n
            if sec=='Другое':
                klass=hb.class_of(p,hb.name_key(p),n)
                other_classes[klass]['files']+=1;other_classes[klass]['bytes']+=n
    temp.replace(source)
    with (output/'Папки.tsv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['Раздел','Папка','Файлов','ГиБ','Оригиналов нет45, ГиБ','Оригиналов нет77, ГиБ','Оригиналы есть на обоих, ГиБ','Без хеша, ГиБ','Разобрать сопоставление, ГиБ'])
        for (sec,folder),v in sorted(folders.items(),key=lambda kv:-kv[1]['bytes']):w.writerow([sec,folder,v['files'],round(v['bytes']/2**30,3),*[round(v[k]/2**30,3) for k in ['missing45_bytes','missing77_bytes','both_bytes','unhashed_bytes','review_bytes']]])
    summary['sections']={k:dict(v) for k,v in sections.items()};summary['other_classes']={k:dict(v) for k,v in other_classes.items()}
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    for sec,v in sections.items():print(sec,v['files'],'files;',round(v['bytes']/2**30,3),'GiB; missing45',round(v['missing45_bytes']/2**30,3),'missing77',round(v['missing77_bytes']/2**30,3),'both',round(v['both_bytes']/2**30,3))
    print('Only cached directory listing was read. No archive disk access.')
