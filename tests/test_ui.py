import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets

import main
from src.context import Paper
from src.settings import Settings
from src.settings_dialog import SettingsDialog


class FakeLLM:
    answer = "**关注点：** 测试回答"

    def __init__(self, settings):
        self.settings = settings

    def get_response(self, prompt, image=None, cancel=None, callback=None,
                     activity_callback=None):
        assert "<discussion>" in prompt
        if callback:
            callback(self.answer)
        return self.answer

    def close(self):
        pass


def test_window_loads_paper_and_slide(monkeypatch, tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(main.Paper, "load", lambda path: Paper(path, ["paper text"]))
    window = main.InterviewAssistantGUI(Settings(api_key=""), register_hotkeys=False)
    image_path = tmp_path / "slide.png"
    image = QtGui.QImage(320, 180, QtGui.QImage.Format_RGB32)
    image.fill(QtCore.Qt.white)
    assert image.save(str(image_path))
    window.load_image(image_path)
    assert window.image_bytes.startswith(b"\x89PNG")
    assert "slide.png" in window.image_label
    window.load_paper(tmp_path / "paper.pdf")
    for _ in range(100):
        app.processEvents()
        if window.paper is not None:
            break
        QtTest.QTest.qWait(20)
    assert window.paper is not None
    assert len(window.paper.pages) == 1
    window.transcription_browser.setPlainText("听众问：两个阶段分别做什么？")
    assert window.revision > 0
    window.close()


def test_manual_request_lifecycle(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(main, "LLMClient", FakeLLM)
    window = main.InterviewAssistantGUI(
        Settings(api_url="http://localhost:8000/v1", api_key=""),
        register_hotkeys=False,
    )
    window.transcription_browser.setPlainText("听众问：为什么要分两个阶段？")
    window.ask(False)
    for _ in range(100):
        app.processEvents()
        if not window.request_id:
            break
        QtTest.QTest.qWait(10)
    assert not window.request_id
    assert "测试回答" in window.current_answer
    assert window.answer_history
    assert not window.cancel_btn.isEnabled()
    window.close()


def test_visual_hierarchy_and_settings_dialog(monkeypatch):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr("src.settings_dialog.list_devices", lambda: [])
    window = main.InterviewAssistantGUI(Settings(), register_hotkeys=False)
    assert window.record_btn.property("role") == "primary"
    assert window.ask_btn.property("role") == "accent"
    assert window.status_label.text().startswith("●")
    assert not window.warning_label.isVisible()
    assert "#6558D3" in window.styleSheet()
    dialog = SettingsDialog(Settings(), window)
    tabs = dialog.findChild(QtWidgets.QTabWidget)
    assert tabs is not None and tabs.count() == 5
    assert tabs.tabText(0) == "模型与连接"
    assert tabs.tabText(3) == "材料与截图"
    assert dialog.model.isEditable()
    dialog.on_models(["Qwen/Test-A", "Qwen/Test-B"], "")
    assert dialog.model.findText("Qwen/Test-B") >= 0
    dialog.model.hidePopup()
    dialog.close()
    window.close()


def test_partial_transcript_is_available_to_manual_request():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = main.InterviewAssistantGUI(Settings(), register_hotkeys=False)
    window.transcription_browser.setPlainText("[10:00:00 · 麦克风] 已确认内容")
    window.on_audio("partial", ("系统声音", 0.0, "听众正在问实验对比"))
    discussion = window.discussion_text()
    assert "已确认内容" in discussion
    assert "[识别中 · 系统声音] 听众正在问实验对比" in discussion
    assert "听众正在问实验对比" in window.live_partial_label.toolTip()
    height = window.live_partial_label.height()
    window.on_audio("partial", ("麦克风", 0.0, "一段更长但不应改变控件高度的实时语音" * 8))
    assert window.live_partial_label.height() == height
    window.close()


def test_maximized_layout_prioritizes_answer_without_overlapping_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = main.InterviewAssistantGUI(Settings(), register_hotkeys=False)
    window.resize(1600, 900)
    window.show()
    app.processEvents()
    actions = [window.record_btn, window.ask_btn, window.capture_btn, window.audio_btn]
    for first in actions:
        for second in actions:
            if first is not second:
                assert not first.geometry().intersects(second.geometry())
    horizontal = window.main_splitter.sizes()
    vertical = window.content_splitter.sizes()
    assert horizontal[0] <= 300
    assert vertical[1] > vertical[0] * 2
    answer_rect = window.llm_response_browser.geometry()
    assert answer_rect.right() <= window.answer_card.width()
    assert answer_rect.bottom() <= window.answer_card.height()
    window.focus_btn.setChecked(True)
    app.processEvents()
    assert not window.left_panel.isVisible()
    assert not window.transcript_card.isVisible()
    window.focus_keep_transcript.setChecked(True)
    app.processEvents()
    assert window.transcript_card.isVisible()
    window.close()


def test_empty_reference_image_setting_clears_active_image(tmp_path):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = main.InterviewAssistantGUI(Settings(reference_image_path=""),
                                        register_hotkeys=False)
    image_path = tmp_path / "slide.png"
    image = QtGui.QImage(80, 50, QtGui.QImage.Format_RGB32)
    image.fill(QtCore.Qt.white)
    assert image.save(str(image_path))
    window.load_image(image_path)
    assert window.image_bytes
    window.load_configured_context()
    assert window.image_bytes is None
    assert window.image_label == ""
    window.close()
