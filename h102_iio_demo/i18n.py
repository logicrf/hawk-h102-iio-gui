"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       i18n.py
@brief      Render UI message templates, switch languages and store the language preference.
@details    Use only on the Qt thread. Retain source templates/arguments without rebuilding widgets
            or accessing devices; store only language and preserve unknown diagnostics/data values.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
import json
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

# Language IDs are UI preferences, never device protocol enums or profile IDs.
LANGUAGES = ('en', 'zh_CN')
ENGLISH = json.loads((Path(__file__).parent / 'translations' / 'en.json').read_text(encoding='utf-8'))
CHINESE = json.loads((Path(__file__).parent / 'translations' / 'zh_CN.json').read_text(encoding='utf-8'))


@dataclass(frozen=True)
class Message:
    """Compose templates while translating nested Messages only, retaining original argument values."""
    source: str
    values: dict[str, Any] = field(default_factory=dict)
    selection: slice | None = None

    def render(self, language: str) -> str:
        """Render the selected locale with original numeric formats and source fallback."""
        catalog = CHINESE if language == 'zh_CN' else ENGLISH
        template = catalog.get(self.source, self.source)
        values = {key: value.render(language) if isinstance(value, Message) else value
                  for key, value in self.values.items()}
        result = template.format(**values) if values else template
        return result[self.selection] if self.selection is not None else result

    def __add__(self, other):
        return message('{left}{right}', left=self, right=other)

    def __radd__(self, other):
        return message('{left}{right}', left=other, right=self)

    def __getitem__(self, selection):
        return Message('{text}', {'text': self}, selection)


def message(source: str, **values) -> Message:
    """Create a deferred template; pass paths, frequencies and diagnostics as placeholder values."""
    return Message(source, values)


def join_messages(separator: str, items) -> Message:
    """Join statistics while retaining each item's original template."""
    values = {f'p{i}': item for i, item in enumerate(items)}
    return message(separator.join('{'+key+'}' for key in values), **values)


def default_settings():
    """Use a dedicated settings domain; tests inject storage without touching real preferences."""
    return QtCore.QSettings('LogicRF', 'Hawk-H102-IIO-GUI')


class LanguageManager(QtCore.QObject):
    """Own current property templates on the main window; language switching updates display only."""
    changed = QtCore.Signal(str)
    storage_failed = QtCore.Signal(str)

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else default_settings()
        saved = self.settings.value('language', 'en')
        self.preferred = saved if saved in LANGUAGES else 'en'
        # Build in the source language, capture static templates, then apply the saved preference once.
        self.language = 'en'
        self._bindings = {}
        app = QtWidgets.QApplication.instance()
        if not hasattr(app, '_h102_qt_translator'):
            app._h102_qt_translator = QtCore.QTranslator(app)
        self._qt_translator = app._h102_qt_translator

    def text(self, source, **values) -> str:
        """Translate immediate dialog text without registering a persistent widget binding."""
        value = message(source, **values) if values else source
        return value.render(self.language) if isinstance(value, Message) else (
            CHINESE if self.language == 'zh_CN' else ENGLISH).get(value, value)

    def bind(self, setter, source, *, key=None):
        """Replace a property's current template without accumulating per-frame history."""
        if key is None:
            key = (id(setter.__self__), setter.__name__)
        self._bindings[key] = (setter, source)
        setter(self.text(source))

    def axis(self, plot, axis, source, **options):
        """Preserve axis units, SI behavior and view range without changing curves or caches."""
        self.bind(partial(plot.setLabel, axis, **options), source, key=(id(plot), 'axis', axis))

    def capture(self, root):
        """Register static source-language widgets without reading input values or credentials."""
        for widget in (root, *root.findChildren(QtWidgets.QWidget)):
            # Qt retranslates tooltips but caches accessible names; register stable object names explicitly.
            scroll_names = {
                'ScrollLeftButton': "Scroll left", 'ScrollRightButton': "Scroll right",
                'qt_dockwidget_floatbutton': "Float", 'qt_dockwidget_closebutton': "Close",
            }
            if widget.objectName() in scroll_names:
                self.bind(widget.setAccessibleName, message(scroll_names[widget.objectName()]))
                continue
            properties = [('toolTip', 'setToolTip'), ('accessibleName', 'setAccessibleName')]
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                properties.append(('text', 'setText'))
            if isinstance(widget, QtWidgets.QGroupBox): properties.append(('title', 'setTitle'))
            if isinstance(widget, (QtWidgets.QDockWidget, QtWidgets.QMainWindow)):
                properties.append(('windowTitle', 'setWindowTitle'))
            if isinstance(widget, QtWidgets.QLineEdit):
                properties.append(('placeholderText', 'setPlaceholderText'))
            if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                properties.append(('suffix', 'setSuffix'))
            for getter, setter in properties:
                value = getattr(widget, getter)()
                key = (id(widget), setter)
                if _has_translation(value) and key not in self._bindings:
                    self.bind(getattr(widget, setter), value)
            if isinstance(widget, QtWidgets.QComboBox):
                for index in range(widget.count()):
                    value = widget.itemText(index)
                    if _has_translation(value):
                        self.bind(partial(widget.setItemText, index), value,
                                  key=(id(widget), 'item', index))
            if isinstance(widget, QtWidgets.QTabWidget):
                for index in range(widget.count()):
                    value = widget.tabText(index)
                    if _has_translation(value):
                        self.bind(partial(widget.setTabText, index), value,
                                  key=(id(widget), 'tab', index))

    def capture_plot(self, plot):
        """Register pyqtgraph titles/legends; bind dynamic axes separately."""
        title = plot.plotItem.titleLabel.text
        self.bind(plot.setTitle, title)
        legend = plot.plotItem.legend
        if legend:
            for _, label in legend.items:
                self.bind(label.setText, label.text)

    def set_language(self, language: str, *, persist=True):
        """Retranslate immediately while blocking widget signals, preventing indirect device actions.

        Store only language; report storage failure while preserving the current in-memory switch.
        """
        if language not in LANGUAGES:
            raise ValueError(f'Unsupported interface language: {language}')
        self.language = language
        app = QtWidgets.QApplication.instance()
        if app is not None and getattr(app, '_h102_qt_language', None) != language:
            app._h102_qt_language = language
            app.removeTranslator(self._qt_translator)
            if language == 'zh_CN':
                directory = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.TranslationsPath)
                if self._qt_translator.load('qtbase_zh_CN', directory):
                    app.installTranslator(self._qt_translator)
        root = self.parent()
        widgets = (root, *root.findChildren(QtWidgets.QWidget)) if root else ()
        blockers = [QtCore.QSignalBlocker(widget) for widget in widgets]
        try:
            for setter, source in tuple(self._bindings.values()): setter(self.text(source))
            # Item-tooltip updates do not emit currentTextChanged; synchronize without business signals.
            for widget in widgets:
                if isinstance(widget, QtWidgets.QComboBox) and not widget.objectName() == 'interface-language':
                    widget.setToolTip(widget.currentText())
        finally:
            del blockers
        if persist:
            self.settings.setValue('language', language)
            self.settings.sync()
            if self.settings.status() != QtCore.QSettings.NoError:
                self.storage_failed.emit(self.text("Could not save language preference; current selection remains active"))
        self.changed.emit(language)


def _has_translation(text):
    """Capture catalog keys only; user input and unknown diagnostics remain literal."""
    return text in ENGLISH or text in CHINESE


# End of file: i18n.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
