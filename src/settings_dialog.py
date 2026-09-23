from dataclasses import replace
import threading
from PyQt5 import QtCore, QtWidgets
from src.audio_capture import list_devices
from src.hotkeys import parse_hotkey
from src.llm_client import LLMClient, safe_error
from src.settings import ROOT
from src.theme import APP_STYLE


class SettingsDialog(QtWidgets.QDialog):
    models_ready = QtCore.pyqtSignal(object, str)
    devices_ready = QtCore.pyqtSignal(object, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.original = settings
        self.result_settings = settings
        self.setWindowTitle("InterPilot 设置")
        self.resize(760, 680)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        eyebrow = QtWidgets.QLabel("INTERPILOT SETTINGS")
        eyebrow.setObjectName("eyebrow")
        title = QtWidgets.QLabel("设置工作方式")
        title.setObjectName("brandTitle")
        subtitle = QtWidgets.QLabel("连接模型、调整提示词，并定义你的音频与快捷键策略。")
        subtitle.setObjectName("brandSubtitle")
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(subtitle)
        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)
        root.addWidget(tabs)
        self.controls = {}
        self.models_ready.connect(self.on_models)
        self.devices_ready.connect(self.on_devices)
        self.model_busy = False
        self.device_busy = False

        def form(title):
            content = QtWidgets.QWidget()
            layout = QtWidgets.QFormLayout(content)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setHorizontalSpacing(18)
            layout.setVerticalSpacing(12)
            layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setWidget(content)
            tabs.addTab(scroll, title)
            return layout

        def line(layout, key, label):
            widget = QtWidgets.QLineEdit(str(getattr(settings, key)))
            layout.addRow(label, widget)
            self.controls[key] = widget
            return widget

        def spin(layout, key, label, minimum, maximum):
            widget = QtWidgets.QSpinBox()
            widget.setRange(minimum, maximum)
            widget.setValue(getattr(settings, key))
            layout.addRow(label, widget)
            self.controls[key] = widget
            return widget

        def combo(layout, key, label, options, editable=False):
            widget = QtWidgets.QComboBox()
            widget.setEditable(editable)
            for caption, value in options:
                widget.addItem(caption, value)
            index = widget.findData(getattr(settings, key))
            if index >= 0:
                widget.setCurrentIndex(index)
            elif editable:
                widget.setCurrentText(getattr(settings, key))
            layout.addRow(label, widget)
            self.controls[key] = widget
            return widget

        def file_input(layout, key, label, file_filter):
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            field = QtWidgets.QLineEdit(str(getattr(settings, key)))
            field.setPlaceholderText("可留空")
            browse = QtWidgets.QPushButton("浏览…")
            browse.clicked.connect(lambda: self.choose_file(key, file_filter))
            clear = QtWidgets.QPushButton("清空")
            clear.setProperty("role", "soft")
            clear.clicked.connect(field.clear)
            row_layout.addWidget(field, 1)
            row_layout.addWidget(browse)
            row_layout.addWidget(clear)
            layout.addRow(label, row)
            self.controls[key] = field
            return field

        connection = form("模型与连接")
        line(connection, "api_url", "API 地址")
        secret = line(connection, "api_key", "API key（本地可留空）")
        secret.setEchoMode(QtWidgets.QLineEdit.Password)
        self.remember = QtWidgets.QCheckBox("用 Windows 账户加密后保存在本机")
        self.remember.setChecked(settings.remember_api_key)
        self.controls["remember_api_key"] = self.remember
        connection.addRow("记住密钥", self.remember)
        note = QtWidgets.QLabel(
            "本地 OpenAI 兼容服务可留空密钥，并把 API 地址设为 http://localhost:端口/v1。"
            "远程服务的密钥不会写入 JSON 或 Git；也可设置 SILICONFLOW_API_KEY 环境变量。"
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        connection.addRow(note)
        self.model = QtWidgets.QComboBox()
        self.model.setEditable(True)
        self.model.addItem(settings.model, settings.model)
        self.model.setCurrentText(settings.model)
        self.controls["model"] = self.model
        model_row = QtWidgets.QWidget()
        model_row_layout = QtWidgets.QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(8)
        model_row_layout.addWidget(self.model, 1)
        choose_model = QtWidgets.QPushButton("选择模型 ▾")
        choose_model.setProperty("role", "soft")
        choose_model.clicked.connect(self.model.showPopup)
        model_row_layout.addWidget(choose_model)
        connection.addRow("回答 / 视觉模型", model_row)
        self.model.setMaxVisibleItems(18)
        self.model.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.model.setToolTip("可直接输入模型 ID；获取列表后可搜索或下拉选择")
        completer = self.model.completer()
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.test = QtWidgets.QPushButton("获取可用模型并选择")
        self.test.setProperty("role", "accent")
        self.test.clicked.connect(self.fetch_models)
        connection.addRow(self.test)
        self.connection_status = QtWidgets.QLabel(
            "可直接输入模型 ID；若服务实现了 /models，获取成功后会打开可搜索的下拉列表。"
            "本地服务不要求鉴权时 API key 留空即可；视觉能力仍需用截图请求验证。"
        )
        self.connection_status.setObjectName("mutedLabel")
        self.connection_status.setWordWrap(True)
        connection.addRow(self.connection_status)
        thinking = QtWidgets.QCheckBox("启用深度思考（会增加首字等待时间）")
        thinking.setChecked(settings.enable_thinking)
        self.controls["enable_thinking"] = thinking
        connection.addRow("推理模式", thinking)
        thinking_budget = spin(connection, "thinking_budget", "思考 token 上限", 128, 32768)
        thinking_budget.setEnabled(settings.enable_thinking)
        thinking.toggled.connect(thinking_budget.setEnabled)
        spin(connection, "max_tokens", "回答 token 上限", 100, 8192)
        spin(connection, "timeout", "请求超时（秒）", 5, 120)

        prompts = form("提示词")
        for key, label in [("system_prompt", "System prompt"), ("user_prompt", "User prompt")]:
            widget = QtWidgets.QPlainTextEdit(getattr(settings, key))
            widget.setMinimumHeight(180 if key == "system_prompt" else 100)
            prompts.addRow(label, widget)
            self.controls[key] = widget

        audio = form("音频与转写")
        self.device_combos = {}
        for source, enabled_key, device_key in [
                ("麦克风 · 我的声音", "mic_enabled", "mic_device"),
                ("系统声音 · 会议音频", "system_enabled", "system_device")]:
            enabled = QtWidgets.QCheckBox("启用")
            enabled.setChecked(getattr(settings, enabled_key))
            device = QtWidgets.QComboBox()
            device.addItem("系统默认设备", -1)
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(enabled)
            row_layout.addWidget(device, 1)
            audio.addRow(source, row)
            self.controls[enabled_key] = enabled
            self.controls[device_key] = device
            self.device_combos[device_key] = device
        self.device_refresh = QtWidgets.QPushButton("刷新音频设备")
        self.device_refresh.clicked.connect(self.fetch_devices)
        audio.addRow("", self.device_refresh)
        self.device_status = QtWidgets.QLabel("正在读取设备…")
        self.device_status.setObjectName("mutedLabel")
        self.device_status.setWordWrap(True)
        audio.addRow("", self.device_status)
        combo(audio, "asr_backend", "语音转写", [("本地 Whisper", "local"), ("云端 API（上传音频）", "cloud")])
        combo(audio, "whisper_model", "Whisper 模型", [(x, x) for x in ["tiny", "base", "small", "medium", "large", "turbo"]], True)
        line(audio, "asr_model", "云端转写模型")
        combo(audio, "language", "本地转写语言", [("自动", "auto"), ("中文", "zh"), ("英文", "en")])
        live_partial = QtWidgets.QCheckBox("边说边显示临时识别，停顿后用完整分段校正")
        live_partial.setChecked(settings.live_partial_enabled)
        self.controls["live_partial_enabled"] = live_partial
        audio.addRow("实时识别", live_partial)
        spin(audio, "partial_interval_ms", "临时结果间隔（毫秒）", 500, 5000)
        spin(audio, "chunk_seconds", "最长分段（秒）", 2, 30)
        spin(audio, "silence_ms", "断句静音时长（毫秒）", 200, 3000)
        spin(audio, "energy_threshold", "静音阈值（PCM RMS）", 0, 5000)
        spin(audio, "auto_interval", "自动检查间隔（秒）", 5, 120)
        spin(audio, "context_chars", "最近讨论字符上限", 1000, 30000)
        spin(audio, "reference_chars", "论文摘录字符上限", 2000, 50000)
        info = QtWidgets.QLabel(
            "本地模型首次使用可能需要下载。临时结果会边说边更新，停顿后由完整分段校正。\n"
            "自动模式仅在有新的最终文本时检查，会上传最近讨论、论文摘录和当前图片。"
        )
        info.setObjectName("mutedLabel")
        info.setWordWrap(True)
        audio.addRow(info)

        materials = form("材料与截图")
        file_input(materials, "paper_path", "论文 PDF", "PDF (*.pdf)")
        page = spin(materials, "paper_page", "优先参考 PDF 页", 0, 9999)
        page.setSpecialValueText("自动")
        file_input(materials, "reference_image_path", "初始参考图片", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        screen_options = []
        for index, screen in enumerate(QtWidgets.QApplication.screens()):
            geometry = screen.geometry()
            primary = " · 主屏" if screen is QtWidgets.QApplication.primaryScreen() else ""
            screen_options.append((
                f"屏幕 {index + 1} · {screen.name()} · {geometry.width()}×{geometry.height()}{primary}",
                screen.name(),
            ))
        if not screen_options:
            screen_options.append(("系统主屏幕", ""))
        screen_combo = combo(materials, "capture_screen_name", "快捷键截图屏幕", screen_options)
        if screen_combo.findData(settings.capture_screen_name) < 0 and settings.capture_screen_name:
            screen_combo.addItem(f"未连接的显示器 · {settings.capture_screen_name}",
                                 settings.capture_screen_name)
            screen_combo.setCurrentIndex(screen_combo.count() - 1)
        combo(materials, "capture_mode", "截图方式", [
            ("直接截取整块屏幕（推荐）", "screen"),
            ("每次手动框选区域", "region"),
        ])
        spin(materials, "image_max_edge", "发送图片最长边", 640, 2560)
        material_note = QtWidgets.QLabel(
            "双屏演讲建议选择正在共享 PPT 的屏幕，并使用整屏截图。快捷键触发后会直接截图并请求提示。"
        )
        material_note.setObjectName("mutedLabel")
        material_note.setWordWrap(True)
        materials.addRow(material_note)

        shortcuts = form("全局快捷键")
        for key, label in [("hotkey_record", "开始 / 暂停监听"), ("hotkey_ask", "立即生成提示"),
                           ("hotkey_capture", "截图并提示"), ("hotkey_toggle", "显示 / 隐藏窗口")]:
            line(shortcuts, key, label)
        shortcut_note = QtWidgets.QLabel("例如 Ctrl+Alt+R；被占用时会提示，可修改后重新注册。")
        shortcut_note.setObjectName("mutedLabel")
        shortcuts.addRow(shortcut_note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        save_button = buttons.button(QtWidgets.QDialogButtonBox.Save)
        save_button.setText("保存设置")
        save_button.setProperty("role", "primary")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.setStyleSheet(APP_STYLE)
        QtCore.QTimer.singleShot(0, self.fetch_devices)

    def values(self):
        values = {}
        for name, widget in self.controls.items():
            if isinstance(widget, QtWidgets.QPlainTextEdit):
                values[name] = widget.toPlainText()
            elif isinstance(widget, QtWidgets.QComboBox):
                values[name] = widget.currentText().strip() if widget.isEditable() else widget.currentData()
            elif isinstance(widget, QtWidgets.QSpinBox):
                values[name] = widget.value()
            elif isinstance(widget, QtWidgets.QCheckBox):
                values[name] = widget.isChecked()
            else:
                values[name] = widget.text().strip()
        return replace(self.original, **values)

    def fetch_models(self):
        settings = self.values()
        self.model_busy = True
        self.test.setEnabled(False)
        self.connection_status.setText("正在获取模型列表…")

        def run():
            client = None
            try:
                client = LLMClient(settings=settings)
                self.models_ready.emit(client.list_models(), "")
            except Exception as exc:
                self.models_ready.emit([], safe_error(exc, settings.api_key))
            finally:
                if client:
                    client.close()
        threading.Thread(target=run, daemon=True).start()

    def choose_file(self, key, file_filter):
        current = self.controls[key].text().strip()
        start = current or str(ROOT / "pre")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择文件", start, file_filter)
        if path:
            self.controls[key].setText(path)

    def fetch_devices(self):
        if self.device_busy:
            return
        self.device_busy = True
        self.device_refresh.setEnabled(False)
        self.device_status.setText("正在读取设备…")

        def run():
            try:
                self.devices_ready.emit(list_devices(), "")
            except Exception as exc:
                self.devices_ready.emit([], safe_error(exc))
        threading.Thread(target=run, daemon=True).start()

    def on_devices(self, devices, error):
        self.device_busy = False
        self.device_refresh.setEnabled(True)
        if error:
            self.device_status.setText("设备读取失败：" + error)
            return
        for key, loopback in [("mic_device", False), ("system_device", True)]:
            combo = self.device_combos[key]
            selected = getattr(self.original, key)
            combo.clear()
            combo.addItem("系统默认设备", -1)
            for device in devices:
                if bool(device.get("isLoopbackDevice")) == loopback:
                    combo.addItem(f"{int(device['index'])}: {device['name']}", int(device["index"]))
            index = combo.findData(selected)
            if index < 0 and selected >= 0:
                combo.addItem(f"未连接的设备 [{selected}]", selected)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
        inputs = sum(not bool(device.get("isLoopbackDevice")) for device in devices)
        outputs = len(devices) - inputs
        self.device_status.setText(f"已找到 {inputs} 个输入设备、{outputs} 个系统回环设备。")

    def on_models(self, models, error):
        self.model_busy = False
        self.test.setEnabled(True)
        if error:
            self.connection_status.setText(error)
            return
        selected = self.model.currentText()
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(selected)
        self.model.view().setMinimumWidth(max(560, self.model.width()))
        self.connection_status.setText(f"连接成功，共 {len(models)} 个模型。请选择或继续输入模型 ID。")
        QtCore.QTimer.singleShot(0, self.model.showPopup)

    def save(self):
        try:
            settings = self.values()
            parsed = [parse_hotkey(getattr(settings, key)) for key in (
                "hotkey_record", "hotkey_ask", "hotkey_capture", "hotkey_toggle")]
            if len(set(parsed)) != len(parsed):
                raise ValueError("四个快捷键不能重复")
            settings.save(persist_secret=True)
            self.result_settings = settings
            self.accept()
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.warning(self, "设置未保存", str(exc))
