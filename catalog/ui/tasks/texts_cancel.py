"""«Копирование»: тексты кнопки «Отменить задание…», окна подтверждения и итога отмены (утверждено владельцем
18.11.2026). Без Qt."""
from .texts_rows import what_where


CANCEL_BTN = 'Отменить задание…'
CANCEL_TIP = ('Отменить задание копирования, которое ждёт запуска, прервано или готово с ошибками. Папка задания '
              'переносится в «Запускаемые скрипты\\_Отменённые»; файлы на дисках не трогаются.')
CANCEL_NONE = ('Отменять нечего: выделите строку или отметьте галочкой задание копирования, которое ждёт запуска, '
               'прервано или готово с ошибками.')
CONFIRM_TITLE = 'Отменить задание?'
CONFIRM_YES, CONFIRM_NO = 'Отменить задание', 'Не отменять'
CONFIRM_NOTE = ('Папка задания будет перенесена в «Запускаемые скрипты\\_Отменённые». Файлы на дисках не трогаются: '
                'уже скопированное останется на архивном диске и будет учтено. Удалить папку можно вручную.')


def _line(r):
    l1, l2 = what_where(r)
    return f'  • {l1} {l2}'


def disabled_tip(bad):
    """Подсказка неактивной кнопки: почему выбранные задания не отменяются. bad - [(строка, причина)]."""
    if not bad:
        return CANCEL_NONE
    return 'Нельзя отменить:\n' + '\n'.join(f'  • {r["task"]} — {why}' for r, why in bad)


def confirm_text(ok, bad):
    """Окно подтверждения: «Будет отменено:», «Не отменяется:» (с причиной) и пояснение."""
    text = CONFIRM_TITLE + '\n\nБудет отменено:\n' + '\n'.join(_line(r) for r in ok)
    if bad:
        text += '\n\nНе отменяется:\n' + '\n'.join(f'{_line(r)} — {why}' for r, why in bad)
    return text + '\n\n' + CONFIRM_NOTE


def result_text(res):
    """Итог одним сообщением: что перенесено и куда, что не перенесено и почему, предупреждения."""
    done = [x for x in res if x['ok']]
    left = [x for x in res if not x['ok']]
    parts = []
    if done:
        parts.append(f'Отменено заданий: {len(done)}.\n' +
                     '\n'.join(f'  • {x["task"]} → {x["dest"]}' for x in done))
    if left:
        parts.append(f'Не отменено: {len(left)}.\n' + '\n'.join(f'  • {x["task"]} — {x["reason"]}' for x in left))
    warns = [x for x in done if x.get('warn')]
    if warns:
        parts.append('Внимание:\n' + '\n'.join(f'  • {x["task"]}: {x["warn"]}' for x in warns))
    return '\n\n'.join(parts) or 'Ничего не отменено.'
