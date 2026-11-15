from __future__ import annotations
import json
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QObject, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QLinearGradient, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QScrollArea, QFileDialog, QMessageBox, QProgressBar)
from backend import investigate

STYLE = '''
QWidget { background: #0b1018; color: #edf2f8; font-family: "Segoe UI", "DejaVu Sans"; font-size: 13px; }
QLabel { background: transparent; }
QFrame#sidebar { background: #101722; border-right: 1px solid #222c3a; }
QFrame#card { background: #121c29; border: 1px solid #253245; border-radius: 16px; }
QFrame#hero { background: #132a32; border: 1px solid #26505a; border-radius: 18px; }
QFrame#card QLabel, QFrame#hero QLabel { background: transparent; border: none; }
QLabel#muted { color: #91a2b8; }
QLabel#eyebrow { color: #66dbc7; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#heading { font-size: 30px; font-weight: 700; }
QLabel#subheading { font-size: 17px; font-weight: 600; }
QPushButton { border: 1px solid #2b3c50; border-radius: 9px; padding: 11px 17px; background: #182333; font-weight: 600; }
QPushButton:hover { background: #24374b; border-color: #55718b; }
QPushButton:disabled { color: #65758a; background: #141e2b; border-color: #263143; }
QPushButton#primary { color: #09231f; background: #64e4c5; border: none; }
QPushButton#primary:hover { background: #92f4dd; }
QPushButton#primary:disabled { background: #28594f; color: #8aafa6; }
QPushButton#nav { text-align: left; padding: 15px; border: none; background: transparent; color: #a0aec2; }
QPushButton#nav:hover { background: #182738; color: #e3effb; }
QPushButton#nav:checked { background: #193a3e; color: #7df1d7; border-left: 3px solid #64e4c5; }
QLineEdit { background: #0c141e; border: 1px solid #34465e; border-radius: 10px; padding: 16px; font-size: 15px; selection-background-color: #295c58; }
QLineEdit:focus { border-color: #64e4c5; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #0b1018; width: 7px; }
QScrollBar::handle:vertical { background: #33445a; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QProgressBar { border: none; background: #1c2b3b; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #64e4c5; }
'''
MODES = {
 'site': ('Веб-сайт', 'Исследуйте цифровой след.', 'Домен, страница, инфраструктура — в одном отчёте.', 'example.com или https://example.com', '01', 'DNS · HTTP · TLS · RDAP'),
 'telegram': ('Telegram', 'Начните с юзернейма.', 'Публичная карточка Telegram без входа в аккаунт.', '@username или https://t.me/username', '02', 'Публичное имя · описание · ссылка'),
 'phone': ('Номер телефона', 'Проверьте номер.', 'Международный формат и сведения из плана нумерации.', '+380… / +7… / +375…', '03', 'Страна · формат · префикс · тип номера'),
}


def label(text, name=None, wrap=False):
    item = QLabel(text)
    item.setTextFormat(Qt.PlainText)
    if name:
        item.setObjectName(name)
    item.setWordWrap(wrap)
    return item


def card():
    frame = QFrame()
    frame.setObjectName('card')
    box = QVBoxLayout(frame)
    box.setContentsMargins(23, 21, 23, 21)
    box.setSpacing(12)
    return frame, box


class Radar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(170, 148)
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = self.rect().center()
        p.setPen(QPen(QColor('#30555c'), 1))
        for radius in (24, 45, 66):
            p.drawEllipse(center, radius, radius)
        p.drawLine(center.x()-72, center.y(), center.x()+72, center.y())
        p.drawLine(center.x(), center.y()-72, center.x(), center.y()+72)
        gradient = QLinearGradient(45, 15, 125, 130)
        gradient.setColorAt(0, QColor('#64e4c5'))
        gradient.setColorAt(1, QColor('#204950'))
        p.setPen(QPen(gradient, 2))
        p.drawLine(center, center + self.rect().topRight()/2 - self.rect().center()/2)
        for x,y,r in ((108,42,4),(52,92,3),(96,94,3)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#64e4c5'))
            p.drawEllipse(x,y,r*2,r*2)
        p.end()


class Worker(QObject):
    success = Signal(dict)
    failure = Signal(str)
    finished = Signal()
    def __init__(self, mode, value):
        super().__init__()
        self.mode, self.value = mode, value
    def run(self):
        try:
            self.success.emit(investigate(self.mode, self.value))
        except Exception as exc:
            self.failure.emit(str(exc))
        finally:
            self.finished.emit()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mode = 'site'
        self.report = None
        self.thread = None
        self.setWindowTitle('osinterz by abjectov')
        self.resize(1200, 850)
        self.setMinimumSize(1020, 730)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(232)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(20,30,20,24)
        sb.setSpacing(9)
        brand = label('◈  osinterz')
        brand.setStyleSheet('font-size: 27px; font-weight: 700; color: #e9fff8; background: transparent;')
        sb.addWidget(brand)
        sb.addWidget(label('       by abjectov', 'muted'))
        sb.addSpacing(38)
        sb.addWidget(label('ИНСТРУМЕНТЫ', 'eyebrow'))
        sb.addSpacing(12)
        self.nav = {}
        for mode, info in MODES.items():
            button = QPushButton(f'{info[4]}   {info[0]}')
            button.setObjectName('nav')
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, m=mode: self.select_mode(m))
            sb.addWidget(button)
            self.nav[mode] = button
        sb.addStretch()
        info, box = card()
        box.setContentsMargins(14,16,14,16)
        box.addWidget(label('PUBLIC SOURCES', 'eyebrow'))
        box.addWidget(label('Открытые данные.\nПроверяемые источники.', 'muted', True))
        sb.addWidget(info)
        sb.addSpacing(12)
        sb.addWidget(label('DESKTOP  /  v1.0', 'muted'))
        layout.addWidget(sidebar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)
        content = QWidget()
        scroll.setWidget(content)
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(34,27,34,25)
        self.body.setSpacing(21)
        top = QHBoxLayout()
        top.addWidget(label('WORKSPACE  /  OPEN SOURCE INTELLIGENCE', 'muted'))
        top.addStretch()
        chip = label('●  БЕЗ API-КЛЮЧЕЙ')
        chip.setStyleSheet('color: #64e4c5; font-size: 10px; letter-spacing: 1px;')
        top.addWidget(chip)
        self.body.addLayout(top)
        hero = QFrame()
        hero.setObjectName('hero')
        hb = QHBoxLayout(hero)
        hb.setContentsMargins(26,20,20,20)
        texts = QVBoxLayout()
        texts.setSpacing(12)
        texts.addWidget(label('OSINTERZ INTELLIGENCE', 'eyebrow'))
        self.heading = label('', 'heading', True)
        texts.addWidget(self.heading)
        self.subtitle = label('', 'muted', True)
        texts.addWidget(self.subtitle)
        hb.addLayout(texts,1)
        hb.addWidget(Radar())
        self.body.addWidget(hero)
        search, box = card()
        self.input_label = label('', 'subheading')
        box.addWidget(self.input_label)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.entry = QLineEdit()
        self.entry.setMaxLength(2048)
        self.entry.returnPressed.connect(self.start)
        row.addWidget(self.entry,1)
        self.run_button = QPushButton('Исследовать  →')
        self.run_button.setObjectName('primary')
        self.run_button.setMinimumHeight(53)
        self.run_button.clicked.connect(self.start)
        row.addWidget(self.run_button)
        box.addLayout(row)
        self.hint = label('', 'muted', True)
        box.addWidget(self.hint)
        self.body.addWidget(search)
        summary = QHBoxLayout()
        self.summary = label('Обзор возможностей', 'subheading')
        summary.addWidget(self.summary)
        summary.addStretch()
        self.export_button = QPushButton('↓  Экспорт JSON')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        summary.addWidget(self.export_button)
        self.body.addLayout(summary)
        self.progress = QProgressBar()
        self.progress.setRange(0,0)
        self.progress.hide()
        self.body.addWidget(self.progress)
        self.status = label('Готов к исследованию. Выберите модуль и введите запрос.', 'muted', True)
        self.body.addWidget(self.status)
        self.results = QVBoxLayout()
        self.results.setSpacing(14)
        self.body.addLayout(self.results)
        self.body.addStretch()
        foot = QHBoxLayout()
        foot.addWidget(label('osinterz by abjectov', 'muted'))
        foot.addStretch()
        foot.addWidget(label('Источники и время проверки — в каждом отчёте', 'muted'))
        self.body.addLayout(foot)
        self.select_mode('site')

    def clear_results(self):
        while self.results.count():
            item = self.results.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def select_mode(self, mode):
        self.mode = mode
        info = MODES[mode]
        for key, button in self.nav.items():
            button.setChecked(key == mode)
        self.heading.setText(info[1])
        self.subtitle.setText(info[2])
        self.input_label.setText(info[0])
        self.entry.clear()
        self.entry.setPlaceholderText(info[3])
        self.hint.setText(info[5])
        self.report = None
        self.export_button.setEnabled(False)
        self.summary.setText('Обзор возможностей')
        self.status.setText('Готов к исследованию. Введите запрос выше.')
        self.status.setStyleSheet('color: #91a2b8;')
        self.clear_results()
        features = {
            'site': [('01 / ИНФРАСТРУКТУРА', 'DNS и хостинг', 'A, AAAA, MX, NS, TXT и CAA — записи домена из DNS.'),
                     ('02 / ВЕБ-ПРИСУТСТВИЕ', 'Страница и защита', 'Заголовок сайта, HTTP-заголовки, TLS и регистрация домена.')],
            'telegram': [('01 / ПУБЛИЧНЫЙ ПРОФИЛЬ', 'Карточка Telegram', 'Опубликованные имя, описание и информация публичной страницы t.me.'),
                         ('02 / ДОСТУПНОСТЬ', 'Результат с источником', 'Недоступная карточка не доказывает отсутствие аккаунта.')],
            'phone': [('01 / ПЛАН НУМЕРАЦИИ', 'Международные номера', 'Украина, Россия, Казахстан, Беларусь и другие страны по коду +…'),
                      ('02 / МЕТАДАННЫЕ', 'Сведения о префиксе', 'Не определяет владельца, активность номера или текущее местоположение.')]
        }
        for eyebrow, title, text in features[mode]:
            frame, box = card()
            box.addWidget(label(eyebrow, 'eyebrow'))
            box.addWidget(label(title, 'subheading'))
            box.addWidget(label(text, 'muted', True))
            self.results.addWidget(frame)

    def start(self):
        if self.thread is not None:
            return
        value = self.entry.text().strip()
        if not value:
            self.status.setText('Введите адрес сайта, юзернейм или номер в выбранном модуле.')
            return
        self.report = None
        self.export_button.setEnabled(False)
        self.clear_results()
        self.summary.setText('Собираем открытые данные')
        self.status.setText('Проверка источников… При недоступности источника появится причина.')
        self.status.setStyleSheet('color: #91a2b8;')
        self.progress.show()
        self.run_button.setEnabled(False)
        for button in self.nav.values():
            button.setEnabled(False)
        self.thread = QThread()
        self.worker = Worker(self.mode, value)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.success.connect(self.show_report)
        self.worker.failure.connect(self.failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished)
        self.thread.start()

    def finished(self):
        self.thread.deleteLater()
        self.thread = None
        self.progress.hide()
        self.run_button.setEnabled(True)
        for button in self.nav.values():
            button.setEnabled(True)

    def failed(self, error):
        self.summary.setText('Не удалось выполнить проверку')
        self.status.setText(error)
        self.status.setStyleSheet('color: #f6ad9d;')

    def show_report(self, report):
        self.report = report
        self.export_button.setEnabled(True)
        self.clear_results()
        sections = report['sections']
        ok = sum(s['status'] == 'ok' for s in sections)
        self.summary.setText('Результат / ' + report['target'])
        self.status.setText(f"Источники: {ok}/{len(sections)} доступны · Время UTC: {report['checked_at'][:19].replace('T', ' ')}")
        for section in sections:
            frame, box = card()
            row = QHBoxLayout()
            row.addWidget(label(section['title'], 'subheading'))
            row.addStretch()
            badge = label('●  ПОЛУЧЕНО' if section['status'] == 'ok' else '●  НЕДОСТУПНО')
            badge.setStyleSheet('font-size: 10px; color: ' + ('#64e4c5;' if section['status'] == 'ok' else '#f6ad9d;'))
            row.addWidget(badge)
            box.addLayout(row)
            grid = QGridLayout()
            grid.setColumnStretch(1,1)
            grid.setHorizontalSpacing(22)
            grid.setVerticalSpacing(13)
            for index, (key,value) in enumerate(section['data'].items()):
                if isinstance(value, bool):
                    value = 'Да' if value else 'Нет'
                elif isinstance(value,(list,dict)):
                    value = json.dumps(value,ensure_ascii=False,indent=2) if value else 'Нет записей'
                elif value is None:
                    value = 'Нет данных'
                grid.addWidget(label(key, 'muted', True),index,0,Qt.AlignTop)
                val = label(str(value),wrap=True)
                val.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(val,index,1)
            box.addLayout(grid)
            source = label('Источник: ' + section['source'], 'muted', True)
            source.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.addWidget(source)
            self.results.addWidget(frame)

    def export(self):
        if not self.report:
            return
        filename, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт', 'osinterz-report.json', 'JSON (*.json)')
        if filename:
            try:
                Path(filename).write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding='utf-8')
                self.status.setText('Отчёт сохранён: ' + filename)
            except OSError as exc:
                QMessageBox.warning(self,'Ошибка сохранения',str(exc))

    def closeEvent(self,event):
        if self.thread is not None:
            self.status.setText('Дождитесь завершения проверки, затем закройте приложение.')
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if '--screenshot' in sys.argv:
        index = sys.argv.index('--screenshot')
        QTimer.singleShot(500, lambda: (window.grab().save(sys.argv[index+1]), app.quit()))
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
