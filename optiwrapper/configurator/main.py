import bisect
import logging
import re
import shlex
import sys
from dataclasses import dataclass
from typing import Any, Iterable, List, NoReturn, Optional

from PySide2.QtCore import QAbstractListModel, QModelIndex, QRegularExpression, Qt
from PySide2.QtGui import QKeySequence, QRegularExpressionValidator
from PySide2.QtWidgets import QApplication, QListWidgetItem, QMainWindow
from Xlib import X, Xatom, display

from .. import hooks
from ..lib import SETTINGS_DIR
from ..libxdo import xdo_select_window_with_click
from ..settings import Config
from .ui.settingswindow import Ui_SettingsWindow

logger = logging.getLogger("optiwrapper.configurator")
logger.setLevel(logging.DEBUG)
logger.propagate = False

Checked = Qt.CheckState.Checked
Unchecked = Qt.CheckState.Unchecked
PartiallyChecked = Qt.CheckState.PartiallyChecked
CONFIG_ROLE = Qt.UserRole + 0


@dataclass
class ConfigEntry:
    config: Config
    _saved_config: Optional[Config]

    @property
    def dirty(self) -> bool:
        return self.config != self._saved_config

    def display_text(self) -> str:
        s = self.config.game
        if self.dirty:
            s += "*"
        return s

    def save(self) -> None:
        self.config.save()
        self._saved_config = self.config.copy()

    def reload(self) -> None:
        if self._saved_config is not None:
            self.config = self._saved_config.copy()


class ConfigModel(QAbstractListModel):  # type: ignore[misc]
    def __init__(self, configs: Iterable[Config] = (), parent: Any = None):
        super().__init__(parent)
        self._entries: List[ConfigEntry] = []
        for config in sorted(configs, key=lambda c: c.game.lower()):
            self._entries.append(ConfigEntry(config, config.copy()))

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        entry = self._entries[index.row()]
        if role == Qt.DisplayRole:
            return entry.display_text()
        if role == CONFIG_ROLE:
            return entry.config
        return None

    def insertRows(
        self, row: int, count: int, parent: QModelIndex = QModelIndex()
    ) -> bool:
        self.beginInsertRows(parent, row, row + count - 1)
        for _ in range(count):
            self._entries.insert(row, None)  # type: ignore[arg-type]
        self.endInsertRows()
        return True

    def add_existing_game(self, game: str) -> QModelIndex:
        return self.add_config(Config.load(game))

    def add_config(self, config: Config, on_disk: bool = True) -> QModelIndex:
        entry = ConfigEntry(config, config.copy() if on_disk else None)
        row = bisect.bisect_left(
            self._entries, config.game.lower(), key=lambda e: e.config.game.lower()
        )
        if (
            row < len(self._entries)
            and self._entries[row].config.game.lower() == config.game.lower()
        ):
            logger.warning("trying to add an already existing game: %s", config.game)
            return self.index(row)
        self.insertRows(row, 1)
        self._entries[row] = entry
        index = self.index(row)
        self.dataChanged.emit(index, index)
        return index

    def reload_config(self, index: QModelIndex) -> None:
        entry = self._entries[index.row()]
        if entry.dirty:
            entry.reload()
            self.dataChanged.emit(index, index)

    def save(self, index: QModelIndex) -> None:
        entry = self._entries[index.row()]
        logger.info("saving:\n%s", entry.config.pretty())
        entry.save()
        # changed dirty flag, so we need to update the display text
        self.dataChanged.emit(index, index)

    def mark_updated(self, index: QModelIndex) -> None:
        self.dataChanged.emit(index, index)

    def get_index(self, game: str) -> QModelIndex:
        if not game:
            return QModelIndex()
        row = bisect.bisect_left(
            self._entries, game.lower(), key=lambda e: e.config.game.lower()
        )
        if self._entries[row].config.game.lower() == game.lower():
            return self.index(row)
        return QModelIndex()


class MainWindow(QMainWindow):  # type: ignore[misc]
    def __init__(self):
        super().__init__()
        # used to disable update signals while we're in the middle of switching games
        self._switching_games = False
        self.current_game = ""

        # enumerate all the hooks so we can include them in the list
        hooks.register_hooks()

        self.ui = Ui_SettingsWindow()
        self.ui.setupUi(self)  # type: ignore[no-untyped-call]
        # keep game picker size fixed when resizing the window
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)

        # set menu bar shortcuts to standard keys
        self.ui.action_reload.setShortcut(QKeySequence.Refresh)
        self.ui.action_exit.setShortcut(QKeySequence.Quit)

        game_id_regex = QRegularExpression(r"[^\s/\\]+")
        game_id_validator = QRegularExpressionValidator(
            game_id_regex, self.ui.game_id_textbox
        )
        self.ui.game_id_textbox.setValidator(game_id_validator)

        self.model = ConfigModel()
        self.ui.game_picker.setModel(self.model)

        # copy tooltips and status tips from text boxes to labels
        for prop in ["command", "process_name", "window_title", "window_class"]:
            label = getattr(self.ui, f"{prop}_label")
            textbox = getattr(self.ui, f"{prop}_textbox")
            label.setToolTip(textbox.toolTip())
            label.setStatusTip(textbox.statusTip())

        # wire up signals for games panel
        self.ui.game_picker.activated.connect(self.game_changed)
        self.ui.add_game_button.clicked.connect(self.new_game)

        # wire up signals for settings panel
        self.ui.command_textbox.editingFinished.connect(self.command_changed)
        self.ui.process_name_textbox.editingFinished.connect(self.process_name_changed)
        self.ui.window_title_textbox.editingFinished.connect(self.window_title_changed)
        self.ui.window_class_textbox.editingFinished.connect(self.window_class_changed)
        self.ui.fill_button.clicked.connect(self.fill_from_window)
        self.ui.flags_list.itemChanged.connect(self.flag_changed)
        self.ui.hooks_list.itemChanged.connect(self.hook_changed)
        self.ui.save_button.clicked.connect(self.save)

        # wire up menu bar signals
        self.ui.action_reload.triggered.connect(self.reload_from_disk)
        self.ui.action_exit.triggered.connect(self.close)

        # add existing games
        for path in SETTINGS_DIR.glob("*.yaml"):
            if path.stem == "sample":
                continue
            self.model.add_existing_game(path.stem)

    def get_current_index(self) -> QModelIndex:
        return self.model.get_index(self.current_game)

    def get_current_config(self) -> Optional[Config]:
        index = self.get_current_index()
        if not index.isValid():
            return None
        config = self.model.data(index, CONFIG_ROLE)
        assert isinstance(config, Config)
        return config

    def new_game(self) -> None:
        game_id = self.ui.game_id_textbox.text()
        if game_id:
            self.ui.game_id_textbox.clear()
            config = Config(game_id)
            index = self.model.add_config(config, on_disk=False)
            self.ui.game_picker.setCurrentIndex(index)
            self.game_changed(index)

    def reload_from_disk(self) -> None:
        index = self.get_current_index()
        if not index.isValid():
            return
        self.model.reload_config(index)
        self.game_changed(index, force=True)

    def game_changed(self, current: QModelIndex, force: bool = False) -> None:
        assert current.isValid()
        config = current.data(CONFIG_ROLE)
        if self.current_game == config.game and not force:
            return
        # clear old settings
        self.current_game = ""
        self.ui.settings_container.setTitle("")
        self.ui.settings_container.setEnabled(False)
        self.clear()
        # fill in new settings
        logger.debug("selection changed to %s", config.game)
        self.ui.command_textbox.setText(shlex.join(config.command))
        self.ui.process_name_textbox.setText(config.process_name)
        self.ui.window_title_textbox.setText(config.window_title)
        self.ui.window_class_textbox.setText(config.window_class)
        self.populate_flags(config)
        self.populate_hooks(config)
        self.current_game = config.game
        self.ui.settings_container.setTitle(config.game)
        self.ui.settings_container.setEnabled(True)

    def clear(self) -> None:
        self.ui.command_textbox.clear()
        self.ui.process_name_textbox.clear()
        self.ui.window_title_textbox.clear()
        self.ui.window_class_textbox.clear()
        self.ui.flags_list.clear()
        self.ui.hooks_list.clear()
        self.ui.hooks_list.setMouseTracking(False)

    def populate_flags(self, config: Config) -> None:
        flags = config.flags
        flags_dict = flags.asdict()

        for name in flags.fields:
            # pylint: disable-next=protected-access
            default = "on" if flags._defaults[name] else "off"
            item = QListWidgetItem(name + f" (default {default})", self.ui.flags_list)
            if name in flags_dict:
                item.setCheckState(Checked if flags_dict[name] else Unchecked)
            else:
                item.setCheckState(PartiallyChecked)
            item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsUserTristate
            )

    def populate_hooks(self, config: Config) -> None:
        enabled_hooks = config.hooks
        self.ui.hooks_list.setMouseTracking(True)

        for name, hook in sorted(hooks.get_all_hooks().items()):
            item = QListWidgetItem(name, self.ui.hooks_list)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            if hook.__doc__:
                item.setToolTip(hook.__doc__)
                item.setStatusTip(hook.__doc__)
            item.setCheckState(Checked if name in enabled_hooks else Unchecked)

    def mark_updated(self) -> None:
        index = self.get_current_index()
        if not index.isValid():
            return
        self.model.mark_updated(index)

    # ==== signal handlers ====

    def command_changed(self) -> None:
        config = self.get_current_config()
        if config is None:
            return
        text = self.ui.command_textbox.text()
        new_command = shlex.split(text)
        if new_command != config.command:
            logger.debug("command changed to %r", text)
            config.command = new_command
            self.mark_updated()

    def process_name_changed(self) -> None:
        config = self.get_current_config()
        if config is None:
            return
        text = self.ui.process_name_textbox.text()
        if text != config.process_name:
            logger.debug("process_name changed to %r", text)
            config.process_name = text
            self.mark_updated()

    def window_title_changed(self) -> None:
        config = self.get_current_config()
        if config is None:
            return
        text = self.ui.window_title_textbox.text()
        if text != config.window_title:
            logger.debug("window_title changed to %r", text)
            config.window_title = text
            self.mark_updated()

    def window_class_changed(self) -> None:
        config = self.get_current_config()
        if config is None:
            return
        text = self.ui.window_class_textbox.text()
        if text != config.window_class:
            logger.debug("window_class changed to %r", text)
            config.window_class = text
            self.mark_updated()

    def flag_changed(self, item: QListWidgetItem) -> None:
        config = self.get_current_config()
        if config is None:
            return
        name = item.text().partition(" ")[0]
        check_state = item.checkState()
        flags_dict = config.flags.asdict()
        if name in flags_dict:
            prev_state = Checked if flags_dict[name] else Unchecked
        else:
            prev_state = PartiallyChecked
        if prev_state == check_state:
            return
        logger.debug(
            "%s: flags.%s changed to %s",
            config.game,
            name,
            {Checked: True, Unchecked: False, PartiallyChecked: None}[check_state],
        )
        if check_state == PartiallyChecked:
            del flags_dict[name]
        else:
            flags_dict[name] = check_state == Checked
        self.mark_updated()

    def hook_changed(self, item: QListWidgetItem) -> None:
        config = self.get_current_config()
        if config is None:
            return
        name = item.text()
        check_state = item.checkState()
        prev_state = Checked if name in config.hooks else Unchecked
        if prev_state == check_state:
            return
        logger.debug(
            "%s: hooks.%s %s",
            config.game,
            name,
            "enabled" if check_state == Checked else "disabled",
        )
        if check_state == Checked:
            config.hooks.append(name)
        elif check_state == Unchecked:
            config.hooks.remove(name)
        else:
            assert False, f"invalid checkState: {check_state}"
        self.mark_updated()

    def fill_from_window(self) -> None:
        """Pick a window and get WM_CLASS and WM_NAME for it."""
        window_id = xdo_select_window_with_click()
        if not window_id:
            return
        disp = display.Display()
        win = disp.create_resource_object("window", window_id)
        # python-xlib has get_wm_name() and get_wm_class(), but they only work
        # with ASCII encoded strings (STRING). Some programs put UTF-8 strings
        # in those properties, so we use AnyPropertyType (the default) instead.
        raw_title = win.get_full_text_property(Xatom.WM_NAME)
        if raw_title is not None:
            window_title = "^" + re.escape(raw_title) + "$"
        else:
            window_title = ""
        # Some programs (e.g. Touhou 6 under wine) put UTF-8 labeled as latin1
        # in WM_CLASS, so try decoding it as UTF-8 first.
        prop = win.get_full_property(Xatom.WM_CLASS, X.AnyPropertyType)
        if prop is None or prop.format != 8:
            window_class = ""
        else:
            try:
                value = prop.value.decode("UTF-8")
            except UnicodeDecodeError:
                value = prop.value.decode("ISO-8859-1")
            parts = value.split("\0")
            if len(parts) < 2:
                window_class = ""
            else:
                window_class = re.escape(parts[0])
        disp.close()
        del win, disp
        logger.debug("setting window title to %s", window_title)
        logger.debug("setting window class to %s", window_class)

        self.ui.window_title_textbox.setText(window_title)
        self.ui.window_title_textbox.editingFinished.emit()
        self.ui.window_class_textbox.setText(window_class)
        self.ui.window_class_textbox.editingFinished.emit()

    def save(self) -> None:
        index = self.get_current_index()
        assert index.isValid()
        self.model.save(index)


def run() -> NoReturn:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("{levelname:.1s}:{name}: {message}", style="{"))
    logger.addHandler(ch)

    app = QApplication(sys.argv)

    window = MainWindow()  # type: ignore
    window.show()

    sys.exit(app.exec_())
