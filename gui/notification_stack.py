from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QWidget


class NotificationStack(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._margin = 12
        self._spacing = 4
        self._max_width = 320
        self._labels: list[QLabel] = []

    def push(self, msg: str):
        label = QLabel(msg, self)
        label.setStyleSheet(
            "background: rgba(50,50,50,230); color: #fff; padding: 6px 10px; "
            "border-radius: 4px; font: 9pt;"
        )
        label.setWordWrap(True)
        label.setMaximumWidth(self._max_width)
        label.show()

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda lbl=label, t=timer: self._pop(lbl, t))
        timer.start(2000)

        self._labels.append(label)
        self._reposition()
        self.show()
        self.raise_()

    def _pop(self, label, timer):
        timer.stop()
        timer.deleteLater()
        if label not in self._labels:
            return
        self._labels.remove(label)
        label.deleteLater()
        self._reposition()
        if not self._labels:
            self.hide()

    def _reposition(self):
        if not self._labels:
            return

        max_lbl_w = 0
        total_h = 0
        for lbl in self._labels:
            lbl.adjustSize()
            max_lbl_w = max(max_lbl_w, lbl.width())
            total_h += lbl.height()

        padding = 16
        spacing_total = self._spacing * (len(self._labels) - 1)
        w = max(max_lbl_w + padding, 100)
        h = total_h + spacing_total + padding

        screen = QApplication.primaryScreen()
        if screen is None:
            return
        ag = screen.availableGeometry()
        max_h = int(ag.height() * 0.6)
        if h > max_h:
            h = max_h

        self.resize(int(w), int(h))

        cy = int(h) - 8
        for lbl in reversed(self._labels):
            lbl_h = lbl.height()
            cy -= lbl_h
            lbl.move(8, cy)
            cy -= self._spacing

        x = ag.right() - int(w) - self._margin
        y = ag.bottom() - int(h) - self._margin
        self.move(int(x), int(y))


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    stack = NotificationStack()
    stack.push("notification self-check")
    assert len(stack._labels) == 1
    label = stack._labels[0]
    timer = stack.findChild(QTimer)
    assert timer is not None and timer.isSingleShot()
    stack._pop(label, timer)
    assert stack._labels == [] and not stack.isVisible()
    stack.close()
    print("notification_stack self-check passed")
