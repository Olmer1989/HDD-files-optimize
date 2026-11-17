"""Секция «Направления» вверху раздела «Обзор» (логика v3, этап 4, 15.11.2026).

Пожелание владельца: назначить диски для конечного копирования (45 и 77 - «Семейный архив», у других направлений -
свои диски), у каждого направления описание «что собирается на этих дисках», галочки «для этих направлений пишем
команды копирования» и кнопка «Перейти к написанию команды на копирование →» (экран «Разбор носителя»).

Таблицу направлений пишет только service (direction_save_preview -> direction_save: предпросмотр, затем под замком
та же проверка и одна строка; копия таблицы - в архив). Этап 5 (15.11.2026): в диалоге нет «Проверить» - «Сохранить»
сразу; переспрос (текст предпросмотра) - только при смене или удалении диска у направления, у которого есть задания или
данные на убираемом диске (service: confirm). «Что копировать» - галочки категорий (hb_core.directions.parse_kind).
Цвета дисков: оранжевый - назначен направлению, зелёный - подключён и свободен, серый - не подключён (disk_ui). Галочки - выбор окна, а не таблица владельца: файл
«_БАЗА\\окно - выбор направлений.json». Экран «Разбор носителя» читает выбор через chosen() (один контракт).
Второй круг замечаний (16.11.2026): «Изменить…» - только карточка (имя, «что собирается», «что копировать»), диски не
показываются и не меняются; смены диска в окне нет - диск выбирается при создании направления или один раз
(«Назначить диск…») у направления без диска; в таблице диски зелёные, оранжевые - только у отмеченных галочкой.
Этап 11 (16.11.2026): секция - карточка «Выберите диск, на который будем копировать»; строка направления отмечается
щелчком целиком; легенда под списком; внизу «Копируем на: …» и «Дальше: выбрать папки на носителе →» (прежняя кнопка
«Перейти к написанию команды…»).
Документ - «Логика_v3_разбор_носителя.md», разделы «Этап 4», «Этап 5», «Этап 7», «Этап 11».
"""
import json
import os
import shutil
import time

from hb_core import api as hb
import service as sv
import disk_ui

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

# Переходник (разбивка 17.11.2026): код - в directions_choice, directions_look, directions_dialog,
# directions_section; здесь прежние имена для прежних импортов.
from directions_choice import (CHOICE_NAME, choice_path, load_choice, save_choice, chosen,
                               section_data)  # noqa: E402,F401
from directions_look import (RAZBOR_PAGE, KINDS, CAT_LABELS, NEAR_TEXT, NEAR_TIP, NEVER_TEXT, GO_TEXT, HEADERS, ON,
                             OFF, gb, kind_text, CHECKED_BG, CARD_BG, CARD_BORDER, TAG_BLUE, TAG_GRAY, TAG_RED,
                             OFF_BADGE, TAG_LABELS, kind_tags, badge_css, FlowLayout, tag_label, disk_row_html,
                             html_esc)  # noqa: E402,F401
from directions_dialog import (_safe, ConfirmDialog, ACK_TEXT, NEW, CARD, ASSIGN, DISKS_LEGEND,
                               DirectionDialog)  # noqa: E402,F401
from directions_section import (DirectionCard, TITLE_TEXT, SUB_TEXT, NONE_TEXT, SECTION_CSS, legend_html,
                                DirectionsSection)  # noqa: E402,F401
