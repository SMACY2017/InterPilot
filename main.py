"""InterPilot desktop presentation assistant."""
import sys
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import markdown2
from PyQt5 import QtCore, QtGui, QtWidgets

from src.audio_capture import AudioSession
from src.context import Paper, build_prompt
from src.hotkeys import Hotkeys
from src.llm_client import LLMClient, safe_error
from src.settings import ROOT, Settings, load_settings
from src.settings_dialog import SettingsDialog
from src.theme import APP_STYLE
from src.transcriber import SpeechTranscriber


class Bridge(QtCore.QObject):
    event = QtCore.pyqtSignal(str, str, object)


class StatusLabel(QtWidgets.QLabel):
    def setText(self, text):
        super().setText(f"●  {text}")


class NoticeLabel(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.hide()

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        super().clear()
        self.hide()


class ElidedLabel(QtWidgets.QLabel):
    """Single-line label that keeps full text in its tooltip."""
    def __init__(self, text=""):
        super().__init__()
        self.full_text = ""
        self.setText(text)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self.refresh_text()

    def refresh_text(self):
        width = max(20, self.contentsRect().width())
        shortened = self.fontMetrics().elidedText(
            self.full_text, QtCore.Qt.ElideMiddle, width
        )
        super().setText(shortened)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_text()


class RegionSelector(QtWidgets.QDialog):
    def __init__(self, screen, pixmap):
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setGeometry(screen.geometry())
        self.setCursor(QtCore.Qt.CrossCursor)
        self.pixmap = pixmap
        self.origin = QtCore.QPoint()
        self.selection = QtCore.QRect()
        self.rubber = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.setPen(QtCore.Qt.white)
        painter.fillRect(0, 0, self.width(), 38, QtGui.QColor(0, 0, 0, 180))
        painter.drawText(20, 25, "拖动选取区域 · Esc 取消")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.origin = event.pos()
            self.rubber.setGeometry(QtCore.QRect(self.origin, QtCore.QSize()))
            self.rubber.show()

    def mouseMoveEvent(self, event):
        self.rubber.setGeometry(QtCore.QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.selection = self.rubber.geometry().intersected(self.rect())
            if self.selection.width() >= 10 and self.selection.height() >= 10:
                self.accept()
            else:
                self.reject()


class InterviewAssistantGUI(QtWidgets.QMainWindow):
    def __init__(self, config=None, register_hotkeys=True):
        super().__init__()
        self.settings = config if isinstance(config, Settings) else load_settings()
        self.setWindowTitle("InterPilot · 论文分享助手")
        self.setWindowIcon(QtGui.QIcon(str(ROOT / "logo.png")))
        self.resize(1280, 900)
        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        self.jobs = {}
        self.dialogs = []
        self.session = None
        self.session_id = ""
        self.session_stopping = False
        self.request_id = ""
        self.request_cancel = None
        self.active_requests = {}
        self.paper = None
        self.paper_load_token = ""
        self.image_bytes = None
        self.image_label = ""
        self.image_pixmap = QtGui.QPixmap()
        self.revision = 0
        self.last_auto_revision = 0
        self.last_auto_time = 0
        self.recent_hints = []
        self.current_answer = ""
        self.request_automatic = False
        self.answer_history = []
        self.live_partials = {}
        self.request_started = 0.0
        self.model_response_ms = None
        self.first_token_ms = None
        self.llm_client = None
        self.llm_signature = None
        self.llm_lock = threading.Lock()
        self.closing = False
        self.capturing = False
        self.focus_mode = False
        self.build_ui()
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, self.settings.stay_on_top)
        self.hotkeys = Hotkeys(self) if register_hotkeys else None
        if self.hotkeys:
            self.configure_hotkeys()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.auto_tick)
        self.timer.start(1000)
        self.render_timer = QtCore.QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.render_answer)
        self.update_context_summary()
        self.load_configured_context()

    def build_ui(self):
        central = QtWidgets.QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        top_bar = QtWidgets.QFrame()
        top_bar.setObjectName("topBar")
        header = QtWidgets.QHBoxLayout(top_bar)
        header.setContentsMargins(2, 0, 2, 0)
        brand = QtWidgets.QVBoxLayout()
        brand.setSpacing(1)
        eyebrow = QtWidgets.QLabel("INTERPILOT")
        eyebrow.setObjectName("eyebrow")
        title = QtWidgets.QLabel("演讲辅助控制台")
        title.setObjectName("brandTitle")
        subtitle = QtWidgets.QLabel("听见讨论，看懂页面，给出有依据的提示")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(eyebrow)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        mode_label = QtWidgets.QLabel("提示策略")
        mode_label.setObjectName("mutedLabel")
        header.addWidget(mode_label)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["半自动 · 快捷键请求", "自动 · 检查新讨论"])
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode.setMinimumWidth(190)
        header.addWidget(self.mode)
        self.pin_check = QtWidgets.QCheckBox("窗口置顶")
        self.pin_check.setChecked(self.settings.stay_on_top)
        self.pin_check.toggled.connect(self.toggle_pin)
        header.addWidget(self.pin_check)
        self.settings_btn = QtWidgets.QPushButton("设置")
        self.settings_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView))
        self.settings_btn.setProperty("role", "quiet")
        self.settings_btn.clicked.connect(self.open_settings)
        header.addWidget(self.settings_btn)
        root.addWidget(top_bar)
        action_bar = QtWidgets.QFrame()
        action_bar.setObjectName("actionBar")
        action_stack = QtWidgets.QVBoxLayout(action_bar)
        action_stack.setContentsMargins(12, 10, 12, 9)
        action_stack.setSpacing(6)
        toolbar = QtWidgets.QGridLayout()
        toolbar.setHorizontalSpacing(7)
        toolbar.setVerticalSpacing(7)
        self.record_btn = QtWidgets.QPushButton("开始监听")
        self.record_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.record_btn.setProperty("role", "primary")
        self.record_btn.clicked.connect(self.toggle_recording)
        self.ask_btn = QtWidgets.QPushButton("立即提示")
        self.ask_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowForward))
        self.ask_btn.setProperty("role", "accent")
        self.ask_btn.clicked.connect(lambda: self.ask(False))
        self.capture_btn = QtWidgets.QPushButton("截图并提示")
        self.capture_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        self.capture_btn.clicked.connect(self.capture)
        self.cancel_btn = QtWidgets.QPushButton("取消回答")
        self.cancel_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogCancelButton))
        self.cancel_btn.setProperty("role", "danger")
        self.cancel_btn.clicked.connect(self.cancel_request)
        self.cancel_btn.setEnabled(False)
        self.audio_btn = QtWidgets.QPushButton("导入音频")
        self.audio_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
        self.audio_btn.clicked.connect(self.import_audio)
        export_btn = QtWidgets.QPushButton("导出会话")
        export_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
        export_btn.clicked.connect(self.export_session)
        for button in [self.record_btn, self.ask_btn, self.capture_btn]:
            button.setFixedHeight(38)
        toolbar.addWidget(self.record_btn, 0, 0)
        toolbar.addWidget(self.ask_btn, 0, 1)
        toolbar.addWidget(self.capture_btn, 1, 0, 1, 2)
        for button in [self.audio_btn, export_btn]:
            button.setFixedHeight(32)
        toolbar.addWidget(self.audio_btn, 2, 0)
        toolbar.addWidget(export_btn, 2, 1)
        self.cancel_btn.setFixedHeight(32)
        toolbar.addWidget(self.cancel_btn, 3, 0, 1, 2)
        self.cancel_btn.hide()
        action_stack.addLayout(toolbar)
        self.mode_note = QtWidgets.QLabel("半自动：手动请求时调用模型")
        self.mode_note.setObjectName("panelCaption")
        action_stack.addWidget(self.mode_note)
        splitter = QtWidgets.QSplitter()
        self.main_splitter = splitter
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        left = QtWidgets.QWidget()
        self.left_panel = left
        left.setMinimumWidth(215)
        left.setMaximumWidth(280)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(action_bar)
        live_card = QtWidgets.QGroupBox("运行状态")
        live_card.setObjectName("statusCard")
        live_card.setMinimumHeight(230)
        live_layout = QtWidgets.QVBoxLayout(live_card)
        live_layout.setContentsMargins(12, 20, 12, 12)
        live_layout.setSpacing(6)
        self.source_meters = {}
        for source, caption in [("麦克风", "麦克风 · 我的声音"),
                                ("系统声音", "系统声音 · 会议")]:
            source_row = QtWidgets.QHBoxLayout()
            source_row.setSpacing(8)
            label = QtWidgets.QLabel(caption)
            label.setObjectName("panelCaption")
            label.setFixedWidth(112)
            meter = QtWidgets.QProgressBar()
            meter.setRange(0, 100)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setFixedHeight(6)
            meter.setProperty("source", "mic" if source == "麦克风" else "system")
            source_row.addWidget(label)
            source_row.addWidget(meter, 1)
            live_layout.addLayout(source_row)
            self.source_meters[source] = meter
        self.live_partial_label = ElidedLabel("等待语音输入")
        self.live_partial_label.setObjectName("livePartial")
        self.live_partial_label.setProperty("state", "idle")
        self.live_partial_label.setFixedHeight(42)
        live_layout.addWidget(self.live_partial_label)
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setObjectName("softDivider")
        live_layout.addWidget(separator)
        context_heading = QtWidgets.QLabel("已载入上下文")
        context_heading.setObjectName("miniTitle")
        live_layout.addWidget(context_heading)
        context_surface = QtWidgets.QFrame()
        context_surface.setObjectName("contextSurface")
        context_surface_layout = QtWidgets.QVBoxLayout(context_surface)
        context_surface_layout.setContentsMargins(9, 7, 9, 7)
        context_surface_layout.setSpacing(3)
        self.paper_label = ElidedLabel("论文 · 未设置")
        self.image_caption = ElidedLabel("画面 · 尚未截图")
        self.screen_caption = ElidedLabel("截图 · 系统主屏幕")
        for label in [self.paper_label, self.image_caption, self.screen_caption]:
            label.setObjectName("contextLine")
            context_surface_layout.addWidget(label)
        live_layout.addWidget(context_surface)
        left_layout.addWidget(live_card)
        left_layout.addStretch()
        splitter.addWidget(left)
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)
        transcript_card = QtWidgets.QGroupBox("讨论上下文")
        transcript_card.setObjectName("transcriptCard")
        self.transcript_card = transcript_card
        transcript_layout = QtWidgets.QVBoxLayout(transcript_card)
        transcript_layout.setContentsMargins(2, 4, 2, 4)
        transcript_layout.setSpacing(6)
        transcript_row = QtWidgets.QHBoxLayout()
        transcript_caption = QtWidgets.QLabel("带时间与通道的转写，可在发送前直接修正")
        transcript_caption.setObjectName("panelCaption")
        transcript_row.addWidget(transcript_caption)
        transcript_row.addStretch()
        clear = QtWidgets.QPushButton("清空讨论")
        clear.setProperty("role", "soft")
        clear.clicked.connect(self.clear_session)
        transcript_row.addWidget(clear)
        transcript_layout.addLayout(transcript_row)
        self.transcription_browser = QtWidgets.QPlainTextEdit()
        self.transcription_browser.setObjectName("transcriptEditor")
        self.transcription_browser.setPlaceholderText("开始监听、导入音频，或在这里输入模拟讨论…")
        self.transcription_browser.document().setMaximumBlockCount(300)
        self.transcription_browser.setMinimumHeight(48)
        self.transcription_browser.textChanged.connect(self.context_changed)
        transcript_layout.addWidget(self.transcription_browser, 1)
        answer_card = QtWidgets.QGroupBox("即时提示")
        answer_card.setObjectName("answerCard")
        self.answer_card = answer_card
        answer_layout = QtWidgets.QVBoxLayout(answer_card)
        answer_layout.setContentsMargins(2, 4, 2, 6)
        answer_layout.setSpacing(6)
        answer_row = QtWidgets.QHBoxLayout()
        answer_intro = QtWidgets.QLabel("为演讲者压缩成可快速扫读的要点")
        answer_intro.setObjectName("panelCaption")
        answer_row.addWidget(answer_intro)
        answer_row.addStretch()
        self.auto_scroll = QtWidgets.QCheckBox("自动滚动")
        self.auto_scroll.setChecked(True)
        answer_row.addWidget(self.auto_scroll)
        self.focus_keep_transcript = QtWidgets.QCheckBox("保留讨论")
        self.focus_keep_transcript.setToolTip("专注阅读时仍显示讨论上下文")
        self.focus_keep_transcript.toggled.connect(self.apply_focus_layout)
        self.focus_keep_transcript.hide()
        answer_row.addWidget(self.focus_keep_transcript)
        self.focus_btn = QtWidgets.QPushButton("专注阅读")
        self.focus_btn.setProperty("role", "focus")
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip("隐藏侧栏和讨论区，让即时提示占满窗口")
        self.focus_btn.toggled.connect(self.toggle_focus_mode)
        answer_row.addWidget(self.focus_btn)
        answer_layout.addLayout(answer_row)
        self.answer_caption = QtWidgets.QLabel("等待请求")
        self.answer_caption.setObjectName("mutedLabel")
        self.answer_caption.setWordWrap(True)
        answer_layout.addWidget(self.answer_caption)
        self.llm_response_browser = QtWidgets.QTextBrowser()
        self.llm_response_browser.setObjectName("answerBrowser")
        self.llm_response_browser.setOpenExternalLinks(False)
        self.llm_response_browser.setPlaceholderText("这里会出现关注点、回答要点和论文出处。")
        self.llm_response_browser.setMinimumHeight(120)
        answer_layout.addWidget(self.llm_response_browser, 1)
        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        content_splitter.addWidget(transcript_card)
        content_splitter.addWidget(answer_card)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 4)
        content_splitter.setSizes([155, 620])
        self.content_splitter = content_splitter
        right_layout.addWidget(content_splitter, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1120])
        status_bar = QtWidgets.QFrame()
        status_bar.setObjectName("statusBar")
        status_layout = QtWidgets.QVBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 7, 12, 7)
        status_layout.setSpacing(4)
        self.status_label = StatusLabel()
        self.status_label.setText("就绪")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.warning_label = NoticeLabel()
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setWordWrap(True)
        status_layout.addWidget(self.warning_label)
        root.addWidget(status_bar)
        self.setStyleSheet(APP_STYLE)

    def background(self, work, done):
        identifier = uuid.uuid4().hex
        self.jobs[identifier] = done
        secret = self.settings.api_key

        def run():
            try:
                result = (work(), "")
            except Exception as exc:
                result = (None, safe_error(exc, secret))
            self.bridge.event.emit("job", identifier, result)
        threading.Thread(target=run, daemon=True).start()

    def on_event(self, kind, identifier, payload):
        if self.closing:
            return
        if kind == "job":
            done = self.jobs.pop(identifier, None)
            if done:
                done(*payload)
            return
        if kind.startswith("audio:"):
            if identifier == self.session_id:
                self.on_audio(kind[6:], payload)
            return
        if kind == "llm_done":
            self.active_requests.pop(identifier, None)
        if identifier != self.request_id:
            return
        if kind == "llm_text":
            self.current_answer += payload
            if not self.request_automatic and not self.render_timer.isActive():
                self.render_timer.start(90)
        elif kind == "llm_activity":
            if self.model_response_ms is None:
                self.model_response_ms = payload
                self.status_label.setText("模型已响应 · 正在思考…")
                if not self.request_automatic:
                    self.answer_caption.setText(
                        self.pending_caption + f" · 响应 {payload / 1000:.1f}s · 思考中"
                    )
        elif kind == "llm_first":
            if self.model_response_ms is None:
                self.model_response_ms = payload
            self.first_token_ms = payload
            self.status_label.setText("模型已响应 · 正在流式生成…")
            if not self.request_automatic:
                self.answer_caption.setText(self.pending_caption + " · " + self.latency_text())
        elif kind == "llm_done":
            self.render_timer.stop()
            self.request_id = ""
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.hide()
            self.settings_btn.setEnabled(self.session is None)
            if payload:
                self.status_label.setText("请求失败")
                self.warning_label.setText(payload)
                return
            answer = self.current_answer.strip()
            normalized = "".join(answer.split())
            if not answer:
                self.status_label.setText("模型未返回可显示的回答，请检查模型及 token 上限")
                return
            if self.request_automatic and ("[NO_HINT]" in answer or normalized in self.recent_hints):
                self.status_label.setText("自动检查完成，暂无新提示")
                return
            self.render_answer()
            total = time.monotonic() - self.request_started
            latency = self.latency_text()
            prefix = f"{latency} · " if latency else ""
            self.answer_caption.setText(self.pending_caption + f" · {prefix}总计 {total:.1f}s")
            self.recent_hints = (self.recent_hints + [normalized])[-5:]
            self.answer_history.append(f"{self.answer_caption.text()}\n\n{answer}")
            self.answer_history = self.answer_history[-100:]
            self.status_label.setText("提示已更新")

    def context_changed(self, *args):
        self.revision += 1

    def mode_changed(self, index):
        if index:
            self.mode_note.setText("自动：出现新讨论时检查提示")
        else:
            self.mode_note.setText("半自动：手动请求时调用模型")
            if self.request_automatic:
                self.cancel_request()

    def current_settings(self):
        return replace(self.settings, stay_on_top=self.pin_check.isChecked())

    def open_settings(self):
        if self.session or self.request_id:
            return
        dialog = SettingsDialog(self.current_settings(), self)
        self.dialogs.append(dialog)  # Keep async model-list requests alive until window closes.
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            previous_signature = self.client_signature(self.settings)
            self.settings = dialog.result_settings
            if previous_signature != self.client_signature(self.settings):
                self.close_llm_client()
            self.configure_hotkeys()
            self.load_configured_context()
            self.update_context_summary()
            self.status_label.setText("设置已保存")

    @staticmethod
    def client_signature(settings):
        return (settings.api_url, settings.api_key, settings.model,
                settings.timeout, settings.max_tokens, settings.system_prompt,
                settings.enable_thinking, settings.thinking_budget)

    def get_llm_client(self, settings):
        signature = self.client_signature(settings)
        with self.llm_lock:
            if self.llm_client is None or self.llm_signature != signature:
                if self.llm_client is not None:
                    self.llm_client.close()
                self.llm_client = LLMClient(settings=settings)
                self.llm_signature = signature
            return self.llm_client

    def close_llm_client(self):
        with self.llm_lock:
            if self.llm_client is not None:
                self.llm_client.close()
            self.llm_client = None
            self.llm_signature = None

    def configure_hotkeys(self):
        self.record_btn.setToolTip(self.settings.hotkey_record)
        self.ask_btn.setToolTip(self.settings.hotkey_ask)
        self.capture_btn.setToolTip(self.settings.hotkey_capture)
        if self.hotkeys:
            errors = self.hotkeys.configure([
                (self.settings.hotkey_record, self.toggle_recording),
                (self.settings.hotkey_ask, lambda: self.ask(False)),
                (self.settings.hotkey_capture, self.capture),
                (self.settings.hotkey_toggle, self.toggle_visibility),
            ])
            self.warning_label.setText("；".join(errors))

    def toggle_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def toggle_focus_mode(self, enabled):
        self.focus_mode = enabled
        self.focus_keep_transcript.setVisible(enabled)
        self.focus_btn.setText("返回布局" if enabled else "专注阅读")
        self.apply_focus_layout()
        if not enabled:
            self.main_splitter.setSizes([240, max(900, self.width() - 240)])
            self.content_splitter.setSizes([155, max(480, self.height() - 340)])

    def apply_focus_layout(self, *args):
        self.left_panel.setVisible(not self.focus_mode)
        keep_transcript = self.focus_mode and self.focus_keep_transcript.isChecked()
        self.transcript_card.setVisible(not self.focus_mode or keep_transcript)

    def toggle_pin(self, enabled):
        visible = self.isVisible()
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, enabled)
        self.settings = replace(self.settings, stay_on_top=enabled)
        try:
            self.settings.save()
        except OSError as exc:
            self.warning_label.setText(f"置顶设置未保存：{exc}")
        if visible:
            self.show()

    def toggle_recording(self):
        if self.session:
            if not self.session_stopping:
                self.session_stopping = True
                self.session.stop()
                self.record_btn.setEnabled(False)
                self.record_btn.setText("正在完成转写…")
                self.record_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
                self.status_label.setText("正在停止采集并处理剩余片段…")
            return
        settings = self.current_settings()
        if not settings.mic_enabled and not settings.system_enabled:
            self.warning_label.setText("请至少勾选一路声音")
            return
        self.settings = settings
        try:
            self.settings.save()
        except OSError as exc:
            self.warning_label.setText(f"设备配置未保存：{exc}")
        identifier = uuid.uuid4().hex
        self.session_id = identifier
        self.session_stopping = False
        self.session = AudioSession(settings, lambda kind, payload:
            self.bridge.event.emit("audio:" + kind, identifier, payload))
        for widget in [self.settings_btn, self.audio_btn]:
            widget.setEnabled(False)
        self.record_btn.setText("暂停监听")
        self.record_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        self.status_label.setText("正在启动音频设备…")
        self.session.start()

    def on_audio(self, kind, payload):
        if kind == "transcript":
            self.live_partials.pop(payload.source, None)
            self.render_live_partials()
            self.transcription_browser.appendPlainText(payload.display())
        elif kind == "partial":
            source, timestamp, text = payload
            self.live_partials[source] = text
            self.render_live_partials()
        elif kind == "level":
            source, level = payload
            meter = self.source_meters.get(source)
            if meter:
                meter.setValue(level)
        elif kind == "warning":
            self.warning_label.setText(payload)
        elif kind == "asr_status":
            self.status_label.setText(payload)
        elif kind == "capture_started":
            self.status_label.setText("正在监听 · 等待语音分段")
        elif kind == "capture_stopped":
            self.status_label.setText("采集已停止 · 正在完成剩余转写")
            self.record_btn.setEnabled(False)
        elif kind == "session_done":
            self.session = None
            self.session_stopping = False
            for widget in [self.audio_btn, self.record_btn]:
                widget.setEnabled(True)
            self.settings_btn.setEnabled(not bool(self.request_id))
            for meter in self.source_meters.values():
                meter.setValue(0)
            self.live_partials.clear()
            self.render_live_partials()
            self.record_btn.setText("开始监听")
            self.record_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
            self.status_label.setText("监听已停止，转写已完成")

    def render_live_partials(self):
        if not self.live_partials:
            state, text = "idle", "等待语音输入"
        else:
            state = "active"
            lines = [f"{source} · {text}" for source, text in self.live_partials.items()]
            text = "  |  ".join(lines)
        if self.live_partial_label.property("state") != state:
            self.live_partial_label.setProperty("state", state)
            self.live_partial_label.style().unpolish(self.live_partial_label)
            self.live_partial_label.style().polish(self.live_partial_label)
        self.live_partial_label.setText(text)

    def discussion_text(self):
        final = self.transcription_browser.toPlainText().strip()
        drafts = "\n".join(
            f"[识别中 · {source}] {text}" for source, text in self.live_partials.items()
        )
        return "\n".join(part for part in (final, drafts) if part).strip()

    def auto_tick(self):
        if (self.mode.currentIndex() != 1 or self.request_id or self.capturing or
                self.revision == self.last_auto_revision or
                not self.transcription_browser.toPlainText().strip() or
                time.monotonic() - self.last_auto_time < self.settings.auto_interval):
            return
        self.ask(True)

    def ask(self, automatic=False):
        if self.capturing or QtWidgets.QApplication.activeModalWidget():
            return
        settings = self.current_settings()
        if len(self.active_requests) >= 2:
            self.status_label.setText("上一个请求正在退出，请稍候")
            return
        self.cancel_request()
        discussion = self.discussion_text()
        if not discussion and not self.image_bytes and not self.paper:
            self.warning_label.setText("请先输入讨论、导入论文或选择图片")
            return
        prompt = build_prompt(settings, discussion, self.paper, settings.paper_page or None,
                              automatic, self.image_label)
        if automatic and self.answer_history:
            prompt += "\n此前已给出的提示（不要重复，除非出现新信息）：\n" + "\n".join(self.answer_history[-2:])[-2500:]
        image = self.image_bytes
        identifier = uuid.uuid4().hex
        cancel = threading.Event()
        self.request_id, self.request_cancel = identifier, cancel
        self.active_requests[identifier] = cancel
        self.request_automatic = automatic
        self.current_answer = ""
        self.request_started = time.monotonic()
        started = self.request_started
        self.model_response_ms = None
        self.first_token_ms = None
        self.last_auto_revision = self.revision
        self.last_auto_time = time.monotonic()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.settings_btn.setEnabled(False)
        self.warning_label.clear()
        self.pending_caption = f"{datetime.now():%H:%M:%S} · {settings.model} · {self.image_label or '无图片'}"
        if not automatic:
            self.answer_caption.setText(self.pending_caption)
            self.llm_response_browser.clear()
        self.status_label.setText("正在检查新讨论…" if automatic else "正在生成提示…")

        def run():
            error = ""
            first = True
            first_activity = True

            def streamed(text):
                nonlocal first
                if first:
                    first = False
                    elapsed = int((time.monotonic() - started) * 1000)
                    self.bridge.event.emit("llm_first", identifier, elapsed)
                self.bridge.event.emit("llm_text", identifier, text)

            def activity():
                nonlocal first_activity
                if first_activity:
                    first_activity = False
                    elapsed = int((time.monotonic() - started) * 1000)
                    self.bridge.event.emit("llm_activity", identifier, elapsed)

            try:
                client = self.get_llm_client(settings)
                client.get_response(prompt, image=image, cancel=cancel,
                    callback=streamed, activity_callback=activity)
            except Exception as exc:
                error = safe_error(exc, settings.api_key)
            finally:
                self.bridge.event.emit("llm_done", identifier, error)
        threading.Thread(target=run, daemon=True, name="llm-request").start()

    def cancel_request(self):
        if self.request_id:
            self.request_cancel.set()
            self.request_id = ""
            self.render_timer.stop()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.hide()
            self.settings_btn.setEnabled(self.session is None)
            self.status_label.setText("已取消显示；后台连接将在收到数据或超时后释放")

    def latency_text(self):
        if self.first_token_ms is None:
            return (f"响应 {self.model_response_ms / 1000:.1f}s"
                    if self.model_response_ms is not None else "")
        if (self.model_response_ms is not None and
                self.first_token_ms - self.model_response_ms >= 200):
            return (f"响应 {self.model_response_ms / 1000:.1f}s · "
                    f"首字 {self.first_token_ms / 1000:.1f}s")
        return f"首字 {self.first_token_ms / 1000:.1f}s"

    def render_answer(self):
        latency = self.latency_text()
        self.answer_caption.setText(
            self.pending_caption + (f" · {latency}" if latency else "")
        )
        scroll = self.llm_response_browser.verticalScrollBar()
        position = scroll.value()
        self.llm_response_browser.setHtml(markdown2.markdown(self.current_answer, safe_mode="escape"))
        scroll.setValue(scroll.maximum() if self.auto_scroll.isChecked() else position)

    def import_paper(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择论文", str(ROOT / "pre"), "PDF (*.pdf)")
        if path:
            self.settings = replace(self.settings, paper_path=path)
            self.settings.save()
            self.load_paper(path)

    def load_paper(self, path):
        path = str(Path(path).resolve())
        if self.paper and str(self.paper.path.resolve()) == path:
            self.update_context_summary()
            return
        self.status_label.setText("正在读取论文…")
        self.paper_label.setText(f"论文 · 正在读取 {Path(path).name}")
        token = uuid.uuid4().hex
        self.paper_load_token = token

        def done(paper, error):
            if token != self.paper_load_token:
                return
            if error:
                self.warning_label.setText(error)
                self.paper_label.setText(f"论文 · 读取失败 {Path(path).name}")
                return
            self.paper = paper
            if self.settings.paper_page > len(paper.pages):
                self.settings = replace(self.settings, paper_page=0)
            self.update_context_summary()
            self.context_changed()
            self.status_label.setText("论文已导入；长文使用关键词选页，可在设置中指定优先页")
        self.background(lambda: Paper.load(path), done)

    def clear_paper(self):
        self.paper_load_token = uuid.uuid4().hex
        self.paper = None
        self.settings = replace(self.settings, paper_path="", paper_page=0)
        self.update_context_summary()
        self.context_changed()

    def open_paper(self):
        if self.paper:
            url = QtCore.QUrl.fromLocalFile(str(self.paper.path.resolve()))
            if self.settings.paper_page:
                url.setFragment(f"page={self.settings.paper_page}")
            QtGui.QDesktopServices.openUrl(url)
        else:
            self.warning_label.setText("请先在设置中选择论文 PDF")

    def import_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择幻灯片截图", str(ROOT / "pre"), "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.settings = replace(self.settings, reference_image_path=path)
            self.settings.save()
            self.load_image(path)

    def load_image(self, path):
        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self.warning_label.setText("图片无法读取，请选择 PNG 或 JPEG")
            return
        self.set_image(pixmap, Path(path).name)

    def set_image(self, pixmap, label):
        edge = self.settings.image_max_edge
        if max(pixmap.width(), pixmap.height()) > edge:
            pixmap = pixmap.scaled(edge, edge, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pixmap.setDevicePixelRatio(1)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        self.image_bytes = bytes(buffer.data())
        self.image_pixmap = pixmap
        self.image_label = f"{label} · {datetime.now():%H:%M:%S}"
        self.update_context_summary()
        self.context_changed()

    def clear_image(self):
        self.image_bytes = None
        self.image_label = ""
        self.image_pixmap = QtGui.QPixmap()
        self.update_context_summary()
        self.context_changed()

    def load_configured_context(self):
        paper_path = self.settings.paper_path.strip()
        if paper_path:
            if Path(paper_path).is_file():
                self.load_paper(paper_path)
            else:
                self.paper_load_token = uuid.uuid4().hex
                self.paper = None
                self.warning_label.setText("设置中的论文文件不存在，请重新选择")
        else:
            self.paper_load_token = uuid.uuid4().hex
            self.paper = None
        image_path = self.settings.reference_image_path.strip()
        if image_path and Path(image_path).is_file():
            self.load_image(image_path)
        elif image_path:
            if self.image_bytes or self.image_label:
                self.clear_image()
            self.warning_label.setText("设置中的参考图片不存在，请重新选择")
        elif self.image_bytes or self.image_label:
            self.clear_image()
        self.update_context_summary()

    def update_context_summary(self):
        if self.paper:
            page = (f" · 第 {self.settings.paper_page} 页"
                    if self.settings.paper_page else " · 自动选页")
            self.paper_label.setText(
                f"论文 · {self.paper.path.name} · {len(self.paper.pages)} 页{page}"
            )
        elif self.settings.paper_path:
            self.paper_label.setText(f"论文 · {Path(self.settings.paper_path).name}")
        else:
            self.paper_label.setText("论文 · 未设置")
        self.image_caption.setText(
            f"画面 · {self.image_label}" if self.image_label else "画面 · 尚未截图"
        )
        screen = self.settings.capture_screen_name or "系统主屏幕"
        mode = "整屏" if self.settings.capture_mode == "screen" else "框选"
        self.screen_caption.setText(f"截图 · {screen} · {mode}")

    def capture_screen(self):
        screens = QtWidgets.QApplication.screens()
        if not screens:
            return None, -1
        wanted = self.settings.capture_screen_name
        screen = next((item for item in screens if item.name() == wanted), None)
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen() or screens[0]
            if wanted:
                self.warning_label.setText("已找不到设置的显示器，本次改用系统主屏幕")
        return screen, screens.index(screen)

    def capture(self):
        if self.capturing or QtWidgets.QApplication.activeModalWidget():
            return
        screen, index = self.capture_screen()
        if screen is None:
            self.warning_label.setText("未找到可截图的显示器")
            return
        self.capturing = True
        visible = self.isVisible()
        covers_window = screen.geometry().intersects(self.frameGeometry())
        if visible and covers_window:
            self.hide()

        def take():
            try:
                pixmap = screen.grabWindow(0)
                if pixmap.isNull():
                    raise ValueError("无法获取屏幕，请改用导入截图")
                if self.settings.capture_mode == "region":
                    selector = RegionSelector(screen, pixmap)
                    if selector.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    rect = selector.selection
                    scale_x = pixmap.width() / screen.geometry().width()
                    scale_y = pixmap.height() / screen.geometry().height()
                    pixmap = pixmap.copy(int(rect.x() * scale_x), int(rect.y() * scale_y),
                                         int(rect.width() * scale_x), int(rect.height() * scale_y))
                self.set_image(pixmap, f"屏幕 {index + 1}")
                QtCore.QTimer.singleShot(0, lambda: self.ask(False))
            except Exception as exc:
                self.warning_label.setText(safe_error(exc))
            finally:
                self.capturing = False
                if visible and covers_window:
                    self.show()
        QtCore.QTimer.singleShot(220 if visible and covers_window else 0, take)

    def import_audio(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择测试音频", str(ROOT / "output"), "音频 (*.wav *.mp3 *.m4a *.flac)")
        if not path:
            return
        settings = self.current_settings()
        self.audio_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        self.status_label.setText("正在转写导入音频…")

        def done(text, error):
            self.audio_btn.setEnabled(True)
            self.record_btn.setEnabled(True)
            if error:
                self.warning_label.setText("转写失败：" + error)
            elif text:
                self.transcription_browser.appendPlainText(f"[导入音频 · {Path(path).name}] {text}")
                self.status_label.setText("音频转写完成")
        self.background(lambda: SpeechTranscriber(settings=settings).transcribe(path), done)

    def clear_session(self):
        if self.session or not self.audio_btn.isEnabled():
            self.warning_label.setText("请先停止监听并等待转写结束，再清空会话")
            return
        self.cancel_request()
        self.transcription_browser.clear()
        self.llm_response_browser.clear()
        self.answer_history.clear()
        self.recent_hints.clear()
        self.live_partials.clear()
        self.render_live_partials()
        self.last_auto_revision = self.revision
        self.answer_caption.setText("新会话 · 保留已导入的论文与图片")

    def export_session(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出会话", str(ROOT / "output" / "session.md"), "Markdown (*.md)")
        if path:
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text("# InterPilot 会话\n\n## 讨论\n\n" +
                    self.transcription_browser.toPlainText() + "\n\n## 提示\n\n" +
                    "\n\n---\n\n".join(self.answer_history), encoding="utf-8")
                self.status_label.setText("会话已导出")
            except OSError as exc:
                self.warning_label.setText(str(exc))

    def closeEvent(self, event):
        self.closing = True
        self.timer.stop()
        self.render_timer.stop()
        for cancel in self.active_requests.values():
            cancel.set()
        if self.session:
            self.session.stop(discard=True)
        if self.hotkeys:
            self.hotkeys.close()
        self.close_llm_client()
        event.accept()


if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication(sys.argv)
    app.setFont(QtGui.QFont("Microsoft YaHei UI", 10))
    try:
        window = InterviewAssistantGUI()
    except Exception as exc:
        QtWidgets.QMessageBox.critical(None, "InterPilot 启动失败", safe_error(exc))
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())
