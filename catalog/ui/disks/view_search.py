"""«Диски и папки»: поиск папок на всех дисках по словам (часть-«примесь» класса DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import service as sv


class SearchView:
    """Часть DisksPage: поиск папок по словам."""

    def find(self):
        words = self.search.text().split()
        if not words:
            return

        def show(rows):
            self.tree.clear()
            self.disk, self.found = None, True
            self.t.blockSignals(True)
            self.t.clearSelection()
            self.t.blockSignals(False)
            self.tree_title.setText(f'Найдено по словам «{" ".join(words)}»')
            self.tree_sum.setText(f'папок: {len(rows)}' + (' (показаны первые 300)' if len(rows) >= 300 else ''))
            self.tree.blockSignals(True)
            for r in rows:
                it = self.folder_item(r['disk'], r['path'], f'{r["disk"]}\\{r["path"]}', r['files'], r['gib'],
                                      r.get('types'), r.get('mark'))         # состав и решение - как в дереве
                self.tree.addTopLevelItem(it)
            self.tree.blockSignals(False)
            self.hash_lab.setText('')
            for d in {r['disk'] for r in rows}:
                self.need_nohash(d)
            self.info.setText(f'Найдено папок: {len(rows)} (вложенные совпадения не показаны). Отметьте нужные '
                              'галочками — действия ниже работают и для найденных папок.')
            self.update_actions()
        self.win.bg.run(sv.find_folders, words, ok=show)
