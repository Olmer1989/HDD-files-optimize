"""Короткий ответ: на экран не больше 20 строк, полный текст - в файл."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import io
from hb_core.consts import MAX_LINES


class ShortAnswer(io.TextIOBase):
    """Поток вывода команды: на экран - первые строки и последние строки ответа (там итог и пути к файлам),
    всё целиком - в «ответы\\последний ответ.txt». Всего на экране не больше MAX_LINES строк."""

    def __init__(self, stream, path, limit=MAX_LINES, tail=6):
        self.stream, self.path, self.head, self.tail = stream, path, limit - tail - 1, tail
        self.lines, self.buf, self.shown, self.last = [], '', 0, collections.deque(maxlen=tail)

    def writable(self):
        return True

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            self.lines.append(line)
            if self.shown < self.head:
                self.emit(line + '\n')
                self.shown += 1
            else:
                self.last.append(line)
        return len(s)

    def emit(self, text=''):
        """На экран; если вывод оборван (окно закрыто, канал закрыт читателем) - молча дальше, полный ответ в файле."""
        try:
            if text:
                self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def flush(self):
        self.emit()

    def close_answer(self):
        if self.buf:
            self.write('\n')
        hidden = len(self.lines) - self.shown - len(self.last)
        if hidden > 0:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text('\n'.join(self.lines) + '\n', encoding='utf-8-sig')
                where = f'полный ответ: {self.path}'
            except OSError:
                where = 'полный ответ сохранить не удалось'
            self.emit(f'... ещё {hidden} строк не показано - {where}\n')
        for line in self.last:
            self.emit(line + '\n')
        self.emit()
