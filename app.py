from functools import partial
import os.path
from pathlib import Path
import signal
import sys
import threading
import traceback

from matplotlib import gridspec
from matplotlib.backends.backend_qtagg import (
    FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
import numpy as np
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QAbstractItemModel, QModelIndex, QEvent, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QKeySequence

from datalog.logfile import LogFile


class Application(QApplication):
    open_file = pyqtSignal(str)

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            self.open_file.emit(event.file())

        return super().event(event)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self._log_file = None
        self._is_graph_empty = True
        self._last_open_dir = None

        file_menu = self.menuBar().addMenu('File')
        open_action = QAction('Open Data Log File', self)
        open_shortcut = QKeySequence(QKeySequence.StandardKey.Open)
        open_action.setShortcut(open_shortcut)
        open_action.triggered.connect(self.open_log_file)
        file_menu.addAction(open_action)

        self.setWindowTitle('Data Log Viewer')
        self.setAcceptDrops(True)

        splitter = QSplitter()

        browser_widget = QWidget()
        browser_layout = QVBoxLayout(browser_widget)
        browser_layout.setContentsMargins(11, 11, 2, 11)

        browser_layout.addWidget(self.create_filter_line_widget())
        self._tree_widget = self.create_tree_widget()
        browser_layout.addWidget(self._tree_widget)
        browser_layout.addWidget(self.create_add_subplot_button())
        browser_layout.addWidget(self.create_clear_button())
        splitter.addWidget(browser_widget)

        self._num_subplots = 1
        self._figure = Figure(figsize=(5, 3))
        open_shortcut_text = open_shortcut.toString(format=QKeySequence.SequenceFormat.NativeText)
        self._figure.suptitle(f'Drag and drop .wpilog file or {open_shortcut_text} to browse')
        self._figure.set_tight_layout(True)
        self._canvas = FigureCanvas(self._figure)
        self._axs = [self._figure.subplots(sharex=True)]
        self._toolbar = NavigationToolbar(self._canvas)

        splitter.addWidget(self.create_graph_widget(self._toolbar, self._canvas))

        self.setCentralWidget(splitter)

        QApplication.instance().open_file.connect(self.load_log_file)

        self.showMaximized()

        if len(sys.argv) == 2:
            self.load_log_file(sys.argv[1])

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and os.path.splitext(urls[0].toLocalFile())[1].lower() == '.wpilog':
            event.acceptProposedAction()

    def dropEvent(self, event):
        filename = event.mimeData().urls()[0].toLocalFile()
        self.load_log_file(filename)
        event.acceptProposedAction()

    def open_log_file(self):
        open_dir = self._last_open_dir if self._last_open_dir is not None else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(self, 'Open Log File', open_dir, 'WPILib Data Log Files (*.wpilog)')

        if not filename:
            return

        self.load_log_file(filename)

    def load_log_file(self, filename):
        try:
            self._log_file = LogFile(filename)
        except:
            self.show_exception_dialog('Error loading data log file')

        self._figure.suptitle(os.path.basename(filename))
        self._last_open_dir = os.path.dirname(filename)
        self.render_tree_widget()
        self.clear_graph()

    def create_filter_line_widget(self):
        filter_line = QLineEdit()
        filter_line.setPlaceholderText('Filter')
        filter_line.textChanged.connect(self.render_tree_widget)

        return filter_line

    def create_tree_widget(self):
        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(['Name', 'Type', 'Record Count'])
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.itemDoubleClicked.connect(self.plot_series)

        return tree

    def render_tree_widget(self, filter_pattern=''):
        if self._log_file is None:
            return

        self._tree_widget.clear()
        entry_tree = self._log_file.get_entry_tree()
        root_item = self.tree_widget_item_from_entry_tree_node(entry_tree, filter_pattern=filter_pattern)
        if root_item is None:
            return

        children = root_item.takeChildren()
        for item in children:
            self._tree_widget.addTopLevelItem(item)

        self._tree_widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._tree_widget.expandAll()

    def create_clear_button(self):
        button = QPushButton('Clear Graph')
        button.clicked.connect(self.clear_graph)

        return button

    def create_add_subplot_button(self):
        button = QPushButton('Add Subplot')
        button.clicked.connect(self.add_subplot)

        return button

    def create_graph_widget(self, toolbar, canvas):
        graph_widget = QWidget()
        graph_layout = QVBoxLayout(graph_widget)
        graph_layout.setContentsMargins(2, 0, 0, 0)
        graph_layout.setSpacing(0)

        graph_layout.addWidget(toolbar)
        graph_layout.addWidget(canvas)

        return graph_widget

    def tree_widget_item_from_entry_tree_node(self, tree_node, filter_pattern='', force_include=False):
        item = QTreeWidgetItem()
        item.setText(0, tree_node.prefix)

        force_include = force_include or filter_pattern.lower() in tree_node.prefix.lower()

        for prefix, entry in tree_node.entries.items():
            if not force_include and filter_pattern.lower() not in prefix.lower():
                continue
            child = QTreeWidgetItem()
            child.setText(0, prefix)
            child.setText(1, entry.type)
            child.setText(2, '{:,}'.format(self._log_file.get_record_count(entry.entry)))
            child.setData(0, Qt.ItemDataRole.UserRole, entry.entry)
            if entry.type in ('string', 'string[]', 'json'):
                child.setDisabled(True)
            item.addChild(child)

        for child_node in tree_node.children.values():
            child = self.tree_widget_item_from_entry_tree_node(
                child_node, filter_pattern=filter_pattern, force_include=force_include)
            if force_include or child is not None:
                item.addChild(child)

        if item.childCount() > 0:
            return item
        return None

    def plot_series(self, item, column):
        if item.isDisabled() or item.data(0, Qt.ItemDataRole.UserRole) is None:
            return

        try:
            entry_id = item.data(0, Qt.ItemDataRole.UserRole)
            entry = self._log_file.get_entry(entry_id)
            name = entry.name
            series = self._log_file.get_series(entry_id)
            ax = self._axs[-1]
            if '[]' in entry.type:
                for i in range(len(series[0])):
                    np_series = np.array([[record[0], record[1][i]] for record in series])
                    ax.step(np_series[:, 0], np_series[:, 1], where='post', label=f'{name}[{i}]')
            else:
                np_series = np.array(series)
                ax.step(np_series[:, 0], np_series[:, 1], where='post', label=name)
            ax.legend()
            ax.autoscale()
            self._toolbar.update()
            self._is_graph_empty = False
            self._canvas.draw()
        except:
            self.show_exception_dialog('Error adding series to graph')

    def retile_subplots(self):
        gs = gridspec.GridSpec(len(self._axs), 1)
        for i, ax in enumerate(self._axs):
            ax.set_position(gs[i].get_position(self._figure))
            ax.set_subplotspec(gs[i])
        self._toolbar.update()

    def add_subplot(self):
        ax = self._figure.add_subplot(len(self._axs) + 1, 1, 1, sharex=self._axs[0])
        self._axs.append(ax)
        self.retile_subplots()
        if not self._is_graph_empty:
            for ax in self._axs:
                ax.autoscale()
        self._canvas.draw()

    def clear_graph(self):
        for i, ax in enumerate(self._axs[1:], 1):
            self._figure.delaxes(ax)
        del self._axs[1:]
        self._axs[0].clear()
        self.retile_subplots()
        self._is_graph_empty = True
        self._canvas.draw()

    def show_exception_dialog(self, text):
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle('Error')
        dialog.setText(text)
        dialog.setInformativeText(traceback.format_exc())
        dialog.exec()


if __name__ == '__main__':
    app = Application(sys.argv)
    w = MainWindow()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app.exec()
