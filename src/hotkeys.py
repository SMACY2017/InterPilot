"""Windows RegisterHotKey integration; no global keyboard hook."""
import ctypes
import sys
from ctypes import wintypes
from PyQt5 import QtCore, QtGui, QtWidgets


def parse_hotkey(text):
    parts = [p.strip().upper() for p in text.split("+")]
    modifiers = {"ALT": 1, "CTRL": 2, "CONTROL": 2, "SHIFT": 4, "WIN": 8}
    mask = 0x4000  # MOD_NOREPEAT
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError(f"未知快捷键修饰符：{part}")
        mask |= modifiers[part]
    key = parts[-1]
    special = {"ENTER": 13, "RETURN": 13, "SPACE": 32, "ESC": 27}
    if key in special:
        code = special[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 111 + int(key[1:])
    else:
        raise ValueError(f"不支持的快捷键：{text}")
    if mask == 0x4000:
        raise ValueError("全局快捷键需要 Ctrl / Alt / Shift / Win 修饰键")
    return mask, code


class Hotkeys(QtCore.QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.callbacks = {}
        self.shortcuts = []
        QtWidgets.QApplication.instance().installNativeEventFilter(self)

    def configure(self, bindings):
        self.clear()
        errors = []
        for index, (text, callback) in enumerate(bindings, 0x4100):
            try:
                modifiers, key = parse_hotkey(text)
                if sys.platform == "win32":
                    if not ctypes.windll.user32.RegisterHotKey(None, index, modifiers, key):
                        raise ValueError(f"快捷键 {text} 被占用，已跳过；可在设置中修改")
                    self.callbacks[index] = callback
                else:
                    shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(text), self.window)
                    shortcut.activated.connect(callback)
                    self.shortcuts.append(shortcut)
            except ValueError as exc:
                errors.append(str(exc))
        return errors

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.callbacks:
                QtCore.QTimer.singleShot(0, self.callbacks[msg.wParam])
                return True, 0
        return False, 0

    def clear(self):
        if sys.platform == "win32":
            for identifier in self.callbacks:
                ctypes.windll.user32.UnregisterHotKey(None, identifier)
        self.callbacks.clear()
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts.clear()

    def close(self):
        self.clear()
        QtWidgets.QApplication.instance().removeNativeEventFilter(self)
