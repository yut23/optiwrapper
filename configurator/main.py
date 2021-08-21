# type: ignore
import sys

from PySide2.QtCore import QFile
from PySide2.QtWidgets import QApplication, QMainWindow

from ui.settingswindow import Ui_SettingsWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.ui = Ui_SettingsWindow()
        self.ui.setupUi(self)
        # keep game picker size fixed when resizing the window
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())
