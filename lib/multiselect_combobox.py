from PyQt6.QtWidgets import QComboBox, QStyledItemDelegate
from PyQt6 import QtGui
from PyQt6.QtGui import QStandardItem, QPalette, QFontMetrics
from PyQt6.QtCore import Qt, QEvent


class MultiSelectComboBox(QComboBox):

    class Delegate(QStyledItemDelegate):
        def sizeHint(self, option, index):
            size = super().sizeHint(option, index)
            size.setHeight(20)
            return size

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.placeholderText = ""
        self.duplicatesEnabled = False

        self.setEditable(True)
        self.lineEdit().setReadOnly(True)


        palette = self.lineEdit().palette()
        palette.setBrush(
            QPalette.ColorRole.Base, palette.brush(QPalette.ColorRole.Button)
        )
        self.lineEdit().setPalette(palette)

        self.setItemDelegate(MultiSelectComboBox.Delegate())

        self.setOutputType("data")
        self.setDisplayType("text")

        self.setDisplayDelimiter(",")

        self.model().dataChanged.connect(self.updateText)
        self.lineEdit().installEventFilter(self)
        self.closeOnLineEditClick = False
        self.view().viewport().installEventFilter(self)

    def setOutputType(self, output_type: str) -> None:
        if output_type in ["data", "text"]:
            self.output_type = output_type
        else:
            raise ValueError("Output type must be 'data' or 'text'")

    def setDisplayType(self, display_type: str) -> None:
        if display_type in ["data", "text"]:
            self.display_type = display_type
        else:
            raise ValueError("Display type must be 'data' or 'text'")

    def getOutputType(self) -> str:
        return self.output_type

    def getDisplayType(self) -> str:
        return self.display_type

    def setDisplayDelimiter(self, delimiter: str, space_after: bool = True, space_before: bool = False) -> None:
        suffix = " " if space_after else ""
        prefix = " " if space_before else ""
        self.display_delimiter = prefix + delimiter + suffix

    def getDisplayDelimiter(self) -> str:
        return self.display_delimiter

    def resizeEvent(self, event) -> None:
        self.updateText()
        super().resizeEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj == self.lineEdit() and event.type() == QEvent.Type.MouseButtonRelease:
            if self.closeOnLineEditClick:
                self.hidePopup()
            else:
                self.showPopup()
            return True
        if obj == self.view().viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            index = self.view().indexAt(event.position().toPoint())
            item = self.model().itemFromIndex(index)
            # Check if item is None:
            if item is None:
                return False
            if item.checkState() == Qt.CheckState.Checked:
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)
            return True
        return False




    def showPopup(self) -> None:
        super().showPopup()
        self.closeOnLineEditClick = True

    def hidePopup(self) -> None:
        super().hidePopup()
        self.startTimer(100)

    def timerEvent(self, event) -> None:
        self.killTimer(event.timerId())
        self.closeOnLineEditClick = False

    def typeSelection(self, index: int, type_variable: str, expected_type: str = "data") -> str:
        """
        Returns the item’s data or text according to the provided type.
        """
        if type_variable == expected_type:
            return self.model().item(index).data()
        return self.model().item(index).text()

    def updateText(self) -> None:
        """
        Update the displayed text based on the selected items.
        If no items are selected, display the placeholder text.
        If one item is selected, display that item's text.
        If multiple items are selected, display the first selected item's text followed by a count, e.g. "clips (2)".
        """
        display_type = self.getDisplayType()
        texts = [
            self.typeSelection(i, display_type)
            for i in range(self.model().rowCount())
            if self.model().item(i).checkState() == Qt.CheckState.Checked
        ]

        if not texts:
            text = self.placeholderText if hasattr(self, 'placeholderText') else ""
        elif len(texts) == 1:
            text = texts[0]
        else:
            text = f"{texts[0]} ({len(texts)})"

        metrics = QFontMetrics(self.lineEdit().font())
        elidedText = metrics.elidedText(
            text, Qt.TextElideMode.ElideRight, self.lineEdit().width()
        )
        self.lineEdit().setText(elidedText)

    def addItem(self, text: str, data: str = None) -> None:
        item = QStandardItem()
        item.setText(text)
        # Store the data (i.e. playlist id) but display only the text.
        item.setData(data if data is not None else text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        self.model().appendRow(item)

    def addItems(self, texts: list, dataList: list = None) -> None:
        dataList = dataList or [None] * len(texts)
        for text, data in zip(texts, dataList):
            self.addItem(text, data)

    def currentData(self) -> list:
        """
        Returns a list of the associated data for the selected items.
        (For example, the playlist ids.)
        """
        output_type = self.getOutputType()
        return [
            self.typeSelection(i, output_type)
            for i in range(self.model().rowCount())
            if self.model().item(i).checkState() == Qt.CheckState.Checked
        ]

    def setCurrentIndexes(self, indexes: list) -> None:
        for i in range(self.model().rowCount()):
            self.model().item(i).setCheckState(
                Qt.CheckState.Checked if i in indexes else Qt.CheckState.Unchecked
            )
        self.updateText()

    def getCurrentIndexes(self) -> list:
        return [i for i in range(self.model().rowCount())
                if self.model().item(i).checkState() == Qt.CheckState.Checked]

    def setPlaceholderText(self, text: str) -> None:
        self.placeholderText = text
        self.updateText()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.updateText()

    def getCurrentOptions(self):
        res = []
        for i in range(self.model().rowCount()):
            if self.model().item(i).checkState() == Qt.CheckState.Checked:
                res.append((self.model().item(i).text(), self.model().item(i).data()))
        return res

    def getPlaceholderText(self):
        return self.placeholderText

    def setDuplicatesEnabled(self, enabled: bool) -> None:
        self.duplicatesEnabled = enabled

    def isDuplicatesEnabled(self) -> bool:
        return self.duplicatesEnabled
    
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        event.ignore()
