from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import re,json,math
root=Path(__file__).parent
docx=next(root.glob('Источники информации по теме*.docx'))
md=next(root.glob('Карта источников*.md')).read_text('utf-8')
N={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','r':'http://schemas.openxmlformats.org/package/2006/relationships'}
with ZipFile(docx) as z:
    bad=z.testzip()
    for p in z.namelist():
        if p.endswith('.xml') or p.endswith('.rels'):E.fromstring(z.read(p))
    tree=E.fromstring(z.read('word/document.xml'))
    rels=E.fromstring(z.read('word/_rels/document.xml.rels'))
    urls={a.get('Target') for a in rels if a.get('Type','').endswith('/hyperlink')}
    hyperlinks=tree.findall('.//w:hyperlink',N)
    paras=tree.findall('.//w:body/w:p',N)
    ids=[s for p in paras if re.match(r'^S\d\d ',s:=''.join(p.itertext()))]
    # Word text nodes only; itertext above may include fields but headings have text only.
    docids=[re.match(r'^(S\d\d) ',s).group(1) for s in ids]
    mdids=re.findall(r'^## (S\d\d) ',md,re.M)
    mdurls=set(re.findall(r'https?://[^\s)]+',md))
    required=set(mdurls)-{'https://github.com/pkolaczk/fclones'}
    # All delivered source link URLs must be represented by external hyperlink relationships.
    missing=required-urls
    assert bad is None
    assert docids==mdids==[f'S{i:02}' for i in range(1,21)],(docids,mdids)
    assert not missing,missing
    assert len(hyperlinks)>=len(urls)
    pg=tree.find('.//w:pgSz',N)
    margins=tree.find('.//w:pgMar',N)
    attrs=lambda e:{E.QName(k).localname:v for k,v in e.attrib.items()}
    stats={'zip_valid':True,'xml_valid':True,'source_ids_match':docids,'external_hyperlinks':len(hyperlinks),'unique_urls':len(urls),'md_urls':len(mdurls),'page_size':attrs(pg),'margins':attrs(margins),'render_status':'NOT VERIFIED: bundled LibreOffice unavailable; render_docx.py failed before conversion.'}
    (root/'qa'/'structural-check.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(stats,ensure_ascii=False))
