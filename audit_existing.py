"""Read existing project exports only; never opens source HDD paths."""
from pathlib import Path
from collections import Counter, defaultdict
import json
from itertools import chain
from openpyxl import load_workbook

base = Path(__file__).resolve().parent
out = base / 'Анализ'
out.mkdir(exist_ok=True)
indexes = {}
summary = {'scope': 'Existing exports only; no source HDD reads', 'indexes': {}, 'workbooks': {}}
for file in sorted(base.glob('index_*.txt')):
    items = []
    malformed = 0
    for line in file.read_text(encoding='utf-8-sig').splitlines():
        if not line:
            continue
        try:
            size, path = line.split('\t', 1)
            items.append((int(size), path, path.replace('/', '\\').rsplit('\\', 1)[-1].lower()))
        except ValueError:
            malformed += 1
    indexes[file.stem[-1]] = items
    counts = Counter((size, name) for size, path, name in items)
    summary['indexes'][file.stem[-1]] = {
        'files': len(items), 'bytes': sum(x[0] for x in items),
        'TiB': round(sum(x[0] for x in items) / 2**40, 4),
        'malformed_lines': malformed,
        'repeated_name_size_extra_entries': sum(n-1 for n in counts.values()),
        'extensions': dict(Counter(Path(x[1]).suffix.lower() for x in items)),
    }
ref = {(s, n) for d in ('G', 'S') for s, p, n in indexes.get(d, [])}
for d in ('D', 'E', 'F'):
    items = indexes.get(d, [])
    matches = [x for x in items if (x[0], x[2]) in ref]
    missing = [x for x in items if (x[0], x[2]) not in ref]
    summary['indexes'][d]['name_size_matches_GS'] = {
        'count': len(matches), 'bytes': sum(x[0] for x in matches),
        'not_matched_count': len(missing), 'not_matched_bytes': sum(x[0] for x in missing)}
for file in sorted(base.glob('*.xlsx')):
    wb = load_workbook(file, read_only=True, data_only=True)
    sheets = []
    for ws in wb:
        rows = ws.iter_rows(values_only=True)
        header = next(rows, ())
        expected_headers = {'Имя файла', 'Путь', 'Имя конечной папки'}
        has_header = bool(header and header[0] in expected_headers)
        if not has_header:
            rows = chain([header], rows)
        count, total, first, pairs = 0, 0, None, Counter()
        embedded_headers = []
        for row_number, row in enumerate(rows, 2 if has_header else 1):
            if not any(v is not None for v in row):
                continue
            if row[0] in expected_headers:
                embedded_headers.append(row_number)
                continue
            count += 1
            if first is None:
                first = row
            if file.name.startswith(('found_', 'missing_')):
                if len(row) > 1 and isinstance(row[1], (int, float)):
                    total += row[1]
                    pairs[(int(row[1]), str(row[5]))] += 1
        sheet = {'sheet': ws.title, 'rows': count, 'has_header': has_header, 'embedded_header_rows': embedded_headers, 'headers': header if has_header else None, 'first_row': first}
        if file.name.startswith(('found_', 'missing_')):
            d = file.stem[-1]
            want_found = file.name.startswith('found_')
            expected = Counter((s,p) for s,p,n in indexes[d] if (((s,n) in ref) == want_found))
            sheet.update(bytes=total, extra_rows_vs_recomputed=sum((pairs-expected).values()), missing_rows_vs_recomputed=sum((expected-pairs).values()))
        sheets.append(sheet)
    summary['workbooks'][file.name] = sheets
    wb.close()
allitems = [x for items in indexes.values() for x in items]
keys = Counter((s,n) for s,p,n in allitems)
sizes = Counter(s for s,p,n in allitems)
summary['all_indexes'] = {
    'files': len(allitems), 'bytes': sum(x[0] for x in allitems),
    'name_size_group_extra_bytes_NOT_confirmed_duplicates': sum(s*(n-1) for (s,name),n in keys.items()),
    'files_with_size_candidates_for_hashing': sum(n for n in sizes.values() if n>1),
    'size_candidate_bytes': sum(s*n for s,n in sizes.items() if n>1),
    'unique_sizes_files_in_these_exports_only': sum(n for n in sizes.values() if n==1),
}
(out / 'audit_existing.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'indexes': summary['indexes'], 'all_indexes': summary['all_indexes'], 'workbooks': {k:[{a:b for a,b in sh.items() if a not in ('first_row',)} for sh in v] for k,v in summary['workbooks'].items()}}, ensure_ascii=False, indent=2))
