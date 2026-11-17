"""Таблица «Диски направлений: что на них лежит по базе» (вынесено из overview_page.py 18.11.2026: таблица теперь в окне
«Содержимое выбранного диска» - disk_content_dialog.py). Числа и подписи (gb_ru, n_ru, files_word) - общие с «Дисками и
папками»; прежние имена отдаёт и overview_page."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hb_core import api as hb  # noqa: E402
import service as sv           # noqa: E402

from PySide6.QtCore import Qt                                                          # noqa: E402
from PySide6.QtGui import QFont, QFontMetrics, QTextDocument                           # noqa: E402
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget   # noqa: E402

from ui_common import gib      # noqa: E402

# Таблица «Диски направлений» (четвёртый круг, 16.11.2026): Диск · Всего, ГБ · «Копии проверены по хешу» (при
# сканировании / скопировано программой) · «Копии не проверены» (сверен только размер / со слов / хеш устарел) ·
# «Хеш не считался» + «Пересканировать». «Подключён» и «Свободно» - в строках направлений.
DISK_GROUPS = (('Копии проверены по хешу', ('при сканировании', 'скопировано программой')),
               ('Копии не проверены', ('сверен только размер', 'со слов «Я сделал в Проводнике»',
                                        'хеш устарел (файл изменён)')))
# в заголовке - переносы, чтобы таблица помещалась при ширине окна 1280
HEAD_BREAKS = {'скопировано программой': 'скопировано<br>программой', 'сверен только размер': 'сверен только<br>размер',
               'со слов «Я сделал в Проводнике»': 'со слов «Я сделал<br>в Проводнике»',
               'хеш устарел (файл изменён)': 'хеш устарел<br>(файл изменён)'}
DISK_HEAD = ['Диск', 'Всего, ГБ', 'при сканировании', 'скопировано программой', 'сверен только размер',
             'со слов «Я сделал в Проводнике»', 'хеш устарел (файл изменён)', 'Хеш не считался']
C_NOHASH = 7
# столбцы 2..6 - степени подтверждения S, C, Z, U, X (буквы владельцу не показываются); Z, U, X - не копия
# подсказки заголовков (16.11.2026, замечание 5 владельца): у каждого столбца - только про свой столбец, 1-2 строки
DISK_TIPS = {
    0: 'Номер диска по журналу сканирования и буква, если диск подключён.',
    1: 'Сколько места занимают все файлы диска по базе.',
    2: 'Хеш посчитан сканером по самому файлу —\nкопия подтверждена.',
    3: 'Скопировано программой со сверкой хеша —\nкопия подтверждена.',
    4: 'При копировании сверен только размер —\nкопия НЕ подтверждена.',
    5: 'Записано вручную в «Я сделал в Проводнике» —\nкопия НЕ подтверждена.',
    6: 'Хеш посчитан, но потом файл изменился (размер или дата).',
    7: 'Хеш у этих файлов не считали (обычно это не фото и не видео).'}
GROUP_TIPS = {'Копии проверены по хешу': 'Копия файла подтверждена по SHA-256.',
              'Копии не проверены': 'Файл в базе есть, но копия хешем не подтверждена.'}
# под таблицей - одна короткая строка на каждое красное число (замечание 4 владельца)
TODO_LINE = {
    4: ('{n} {files} — при копировании сверен только размер, копия не подтверждена',
        'пересчитать хеши (пересканировать с «Перечитать всё»)'),
    5: ('{n} {files} {checked} — {written} вручную в «Я сделал в Проводнике»', 'пересканировать эти папки'),
    6: ('у {n} {files_gen} хеш устарел — файл изменён после подсчёта', 'пересканировать эти папки')}
RED = '#c62828'


def gb_ru(x):
    """15,9 - как пишет владелец."""
    return gib(x).replace('.', ',')


def n_ru(n):
    return f'{n or 0:,}'.replace(',', ' ')


def shown_disks(dirs, checked):
    """Прежняя нижняя таблица «Обзора» (с 18.11.2026 на экране не используется: окно «Содержимое выбранного диска»
    показывает диски одной карточки): диски отмеченных направлений по порядку; ничего не отмечено - диски всех
    направлений, у которых есть диск. Отмеченное направление без диска (в окне его отметить нельзя, но файл выбора могли поправить
    или диск сняли командой) - в приписку «у А… диск не назначен». -> (диски, показаны ли все, приписка)."""
    want = set(checked)
    marked = [d for n, d in dirs.items() if n in want]
    every = not marked
    pick = [d for d in dirs.values() if d.disks] if every else marked
    disks = list(dict.fromkeys(x for d in pick for x in d.disks))
    if every:
        note = 'галочек нет — показаны все' if disks else ''
    else:
        from directions_look import show_num        # «Н1» на экране - «А1» (17.11.2026)
        note = '; '.join(f'у {show_num(d.num)} диск не назначен' for d in marked if not d.disks)
    return disks, every, note


def disk_rows(disks, info):
    """Строки таблицы дисков: [dict(disk, cells=[8 текстов], red={столбцы}, nohash=число)]."""
    out = []
    for d in disks:
        m = info[d]
        ev = m['ev']
        nums = [ev.get(k, 0) for k in sv.EV_COLS + (hb.EV_NONE,)]
        name = f'{d} · {m["letter"]}' if m.get('letter') else d
        cells = [name, gb_ru(m['gib'])] + [n_ru(x) for x in nums]
        red = {j for j in (4, 5, 6) if nums[j - 2]}
        out.append(dict(disk=d, cells=cells, red=red, nohash=nums[-1], in_base=bool(m.get('in_base')), nums=nums))
    return out


def files_word(n):
    n = abs(int(n or 0))
    if n % 10 == 1 and n % 100 != 11:
        return 'файл'
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 'файла'
    return 'файлов'


def todo_items(rows):
    """Что сделать с красными числами: [(диск, столбец, текст строки, текст действия)] - по строке на число."""
    out = []
    for r in rows:
        for j in sorted(r['red']):
            n = r['nums'][j - 2]
            what, act = TODO_LINE[j]
            one = n % 10 == 1 and n % 100 != 11
            out.append((r['disk'], j, what.format(n=n_ru(n), files=files_word(n), files_gen='файла' if one else 'файлов',
                                                  checked='не проверен' if one else 'не проверены',
                                                  written='записан' if one else 'записаны'), act))
    return out


def rescan_tip(disk, n):
    """Подсказка кнопки «Пересканировать» - по пунктам."""
    gen = 'файла' if n % 10 == 1 and n % 100 != 11 else 'файлов'
    return (f'Пересканировать {disk}\n• посчитает хеш у {n_ru(n)} {gen} без хеша\n'
            '• нужен подключённый диск\n• откроет «Диски и папки» с этим диском')


def disk_table_html(rows):
    """HTML-таблица с двухуровневым заголовком; ненулевые «не проверены» - красным; «Хеш не считался» - ссылка."""
    import html as h
    th = 'style="background:#eef2f6; color:#333; font-weight:bold; padding:4px 8px"'
    th2 = 'style="background:#f6f8fa; color:#444; padding:3px 8px; font-weight:normal"'
    out = ['<table cellspacing="0" cellpadding="0" border="1" style="border-collapse:collapse; border-color:#d0d7de">',
           f'<tr><th rowspan="2" align="left" {th}>Диск</th><th rowspan="2" {th}>Всего, ГБ</th>']
    for title, subs in DISK_GROUPS:
        out.append(f'<th colspan="{len(subs)}" {th}>{h.escape(title)}</th>')
    out.append(f'<th rowspan="2" {th}>Хеш не<br>считался</th></tr><tr>')
    for _title, subs in DISK_GROUPS:
        for s in subs:
            out.append(f'<th {th2}>{HEAD_BREAKS.get(s, h.escape(s))}</th>')
    out.append('</tr>')
    for r in rows:
        c = r['cells']
        name = h.escape(c[0]) + ('' if r['in_base'] else ' <span style="color:#8a8a8a">(нет описи)</span>')
        out.append(f'<tr><td style="padding:4px 8px"><b>{name}</b></td>')
        for j in range(1, C_NOHASH):
            v = h.escape(c[j])
            if j in r['red']:
                v = f'<b style="color:{RED}">{v}</b>'
            out.append(f'<td align="right" style="padding:4px 8px">{v}</td>')
        v = h.escape(c[C_NOHASH])
        if r['nohash']:
            v += f' · <a href="rescan:{h.escape(r["disk"])}">Пересканировать</a>'
        out.append(f'<td align="right" style="padding:4px 8px">{v}</td></tr>')
    out.append('</table>')
    return ''.join(out)


def todo_html(rows):
    """Под таблицей - по короткой строке на каждое красное число: «⚠ HDD55: 432 файла не проверены — записаны вручную
    в «Я сделал в Проводнике». Что сделать: пересканировать эти папки → Перейти» (ссылка - «Диски и папки» с этим
    диском). Раньше здесь была общая «стена текста» по столбцам (замечание 4 владельца, 16.11.2026)."""
    import html as h
    lines = [f'<span style="color:{RED}">⚠</span> <b>{h.escape(d)}</b>: {h.escape(what)}. Что сделать: {h.escape(act)} → '
             f'<a href="rescan:{h.escape(d)}">Перейти</a>' for d, _j, what, act in todo_items(rows)]
    return '<br>'.join(lines)


class DiskTable(QFrame):
    """Таблица «Диски направлений» из настоящих виджетов (16.11.2026, замечания 4-5 владельца): двухуровневый
    заголовок, у каждого заголовка - своя короткая подсказка (общей подсказки на всю таблицу нет); столбец «Диск» по
    самому длинному имени («HDD55 · I:» не обрезается); «Пересканировать» - маленькая кнопка с подсказкой по пунктам
    (открывает «Диски и папки» с этим диском, on_rescan)."""
    LINE = '#d0d7de'

    def __init__(self, on_rescan):
        super().__init__()
        self.on_rescan = on_rescan
        self.setObjectName('disktable')
        self.setStyleSheet(f'QFrame#disktable {{ border:1px solid {self.LINE}; background:#ffffff; }}')
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.heads, self.buttons, self.cells, self.rows = {}, {}, [], []

    def _cell(self, text, r, c, rs=1, cs=1, head=False, sub=False, right=False, tip=''):
        lab = QLabel(text)
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(False)
        bg = '#eef2f6' if head else '#f6f8fa' if sub else '#ffffff'
        weight = 'bold' if head else 'normal'
        lab.setStyleSheet(f'QLabel {{ background:{bg}; font-weight:{weight}; padding:4px 8px; '
                          f'border-right:1px solid {self.LINE}; border-bottom:1px solid {self.LINE}; }}')
        al = Qt.AlignRight if right else (Qt.AlignHCenter if (head or sub) and c else Qt.AlignLeft)
        lab.setAlignment(al | Qt.AlignVCenter)
        if tip:
            lab.setToolTip(tip)
        self.grid.addWidget(lab, r, c, rs, cs)
        return lab

    def clear(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.heads, self.buttons, self.cells = {}, {}, []

    def set_rows(self, rows):
        import html as h
        self.clear()
        self.rows = rows
        self.heads['Диск'] = self._cell('Диск', 0, 0, 2, 1, head=True, tip=DISK_TIPS[0])
        self.heads['Всего, ГБ'] = self._cell('Всего, ГБ', 0, 1, 2, 1, head=True, tip=DISK_TIPS[1])
        col = 2
        for title, subs in DISK_GROUPS:
            self.heads[title] = self._cell(h.escape(title), 0, col, 1, len(subs), head=True, tip=GROUP_TIPS[title])
            for k, s_ in enumerate(subs):
                self.heads[s_] = self._cell(HEAD_BREAKS.get(s_, h.escape(s_)), 1, col + k, sub=True,
                                            tip=DISK_TIPS[DISK_HEAD.index(s_)])
            col += len(subs)
        self.heads['Хеш не считался'] = self._cell('Хеш не<br>считался', 0, col, 2, 1, head=True, tip=DISK_TIPS[C_NOHASH])
        fm = QFontMetrics(self.font())
        bold = QFont(self.font())
        bold.setBold(True)
        fmb = QFontMetrics(bold)
        name_w = max([fmb.horizontalAdvance(r['cells'][0]) + (0 if r['in_base'] else fm.horizontalAdvance(' (нет описи)'))
                      for r in rows] + [fm.horizontalAdvance('Диск')]) + 24
        self.grid.setColumnMinimumWidth(0, name_w)
        for i, r in enumerate(rows):
            c = r['cells']
            name = '<b>' + h.escape(c[0]) + '</b>' + ('' if r['in_base'] else ' <span style="color:#8a8a8a">(нет описи)</span>')
            line = [self._cell(name, 2 + i, 0)]
            for j in range(1, C_NOHASH):
                v = h.escape(c[j])
                if j in r['red']:
                    v = f'<b style="color:{RED}">{v}</b>'
                line.append(self._cell(v, 2 + i, j, right=True))
            box = QWidget()
            box.setObjectName('nohash')
            box.setStyleSheet(f'QWidget#nohash {{ background:#ffffff; border-right:1px solid {self.LINE}; '
                              f'border-bottom:1px solid {self.LINE}; }}')
            hl = QHBoxLayout(box)
            hl.setContentsMargins(8, 2, 6, 2)
            hl.setSpacing(6)
            num = QLabel(h.escape(c[C_NOHASH]))
            num.setStyleSheet('background:transparent; border:none')
            hl.addStretch(1)
            hl.addWidget(num)
            if r['nohash']:
                b = QPushButton('Пересканировать')
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet('QPushButton { font-size:8pt; padding:1px 8px; border:1px solid #1e88e5; '
                                'border-radius:4px; color:#0d47a1; background:#e3f2fd; }'
                                'QPushButton:hover { background:#bbdefb; }')
                b.setToolTip(rescan_tip(r['disk'], r['nohash']))
                b.clicked.connect(lambda _=False, d=r['disk']: self.on_rescan(d))
                hl.addWidget(b)
                self.buttons[r['disk']] = b
            self.grid.addWidget(box, 2 + i, C_NOHASH)
            line.append(num)
            self.cells.append(line)

    def text(self):
        """Текст таблицы построчно (для проверок): ячейки через « | »."""
        doc = QTextDocument()
        out = []
        for lab in self.heads.values():
            doc.setHtml(lab.text())
            out.append(doc.toPlainText())
        lines = [' | '.join(out)]
        for line in self.cells:
            vals = []
            for lab in line:
                doc.setHtml(lab.text())
                vals.append(doc.toPlainText())
            lines.append(' | '.join(vals))
        return '\n'.join(lines)

