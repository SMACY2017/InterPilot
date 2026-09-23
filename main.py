import sys
import threading
import time
import ctypes

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMainWindow, QWidget, QGridLayout, QPushButton, QCheckBox, QTextBrowser, QLabel

import markdown2  # 请使用 pip install markdown2 安装此包

from src.audio_capture import LoopbackRecorder
from src.transcriber import SpeechTranscriber
from src.llm_client import LLMClient
import os
import configparser

#获取当前文件的绝对路径，向上一级，用绝对路径找到config.ini并读取
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = current_dir
config_path = os.path.join(project_root, 'config.ini')
MYCONFIG = configparser.ConfigParser()
MYCONFIG.read(config_path,encoding='utf-8')


# RecorderThread 保持不变，全部录音操作在同一线程内进行
class RecorderThread(threading.Thread):
    def __init__(self, recorder, filename, duration=None):
        super().__init__()
        self.recorder = recorder
        self.filename = filename
        self.duration = duration

    def run(self):
        try:
            self.recorder.start_recording(self.filename)
            self.recorder.record(duration=self.duration)
        finally:
            self.recorder._cleanup()  # 在同一线程中释放资源

# 利用 Windows API 防止屏幕捕获
def prevent_screen_capture(winId):
    try:
        WDA_MONITOR = 1  # 仅在支持该API的 Windows 系统有效
        ctypes.windll.user32.SetWindowDisplayAffinity(int(winId), WDA_MONITOR)
    except Exception as e:
        print("屏幕保护设置失败:", e)

class InterviewAssistantGUI(QMainWindow):
    def __init__(self,config):
        super().__init__()
        self.setWindowTitle("InterPolit")
        #设置图标
        self.setWindowIcon(QtGui.QIcon('logo.png'))
        self.setGeometry(100, 100, 1200, 900)
        # 创建中心控件与布局
        central = QWidget()
        self.setCentralWidget(central)
        layout = QGridLayout(central)
        
        # 状态变量与模块初始化
        self.recorder = None
        self.recording_thread = None
        self.current_filename = ""
        self.llm_full_text = ""
        self.llm_client_ask_cnt = 1
        self.default_prompt = MYCONFIG['DEFAULT']['DEFAULT_PROMPT']
        
        self.transcriber = SpeechTranscriber()
        self.llm_client = LLMClient()  # 替换为你的 API key
        
        # 按钮与控件
        self.start_btn = QPushButton("开始录音")
        self.start_btn.clicked.connect(self.start_recording)
        layout.addWidget(self.start_btn, 0, 0)
        
        self.stop_btn = QPushButton("结束录音")
        self.stop_btn.clicked.connect(self.stop_recording)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn, 0, 1)
        
        self.transcribe_btn = QPushButton("转写文字")
        self.transcribe_btn.clicked.connect(self.transcribe_audio)
        self.transcribe_btn.setEnabled(False)
        layout.addWidget(self.transcribe_btn, 0, 2)
        
        self.send_llm_btn = QPushButton("发送给 LLM")
        self.send_llm_btn.clicked.connect(self.send_to_llm)
        self.send_llm_btn.setEnabled(False)
        layout.addWidget(self.send_llm_btn, 0, 3)
        
        self.auto_transcribe_chk = QCheckBox("结束录音后自动转文字")
        self.auto_transcribe_chk.setChecked(True)
        layout.addWidget(self.auto_transcribe_chk, 1, 0, 1, 2)
        
        self.auto_send_llm_chk = QCheckBox("转文字后自动发送给 LLM")
        self.auto_send_llm_chk.setChecked(True)
        layout.addWidget(self.auto_send_llm_chk, 1, 1, 1, 2)

        #创建是否自动滚动scrollbar的勾选框
        self.auto_scroll_chk = QCheckBox("自动滚动")
        self.auto_scroll_chk.setChecked(True)
        #放在第一行第三列
        layout.addWidget(self.auto_scroll_chk, 1, 2,1,2)
        
        # 转写文本显示区域
        self.transcription_browser = QTextBrowser()
        self.transcription_browser.setPlaceholderText("转写内容将显示在这里...")
        #设置为可编辑
        self.transcription_browser.setReadOnly(False)
        #设置为可拖拽
        self.transcription_browser.setAcceptDrops(True)
        layout.addWidget(self.transcription_browser, 2, 0, 1, 4)
        # 高度固定

        self.transcription_browser.setFixedHeight(150)  # 或者使用 setMinimumHeight(150)
        # LLM 回复区域：支持 Markdown 渲染
        self.llm_response_browser = QTextBrowser()
        self.llm_response_browser.setPlaceholderText("LLM回复将显示在这里（支持Markdown）...")

        #设置为可拖拽
        self.llm_response_browser.setAcceptDrops(True)
        layout.addWidget(self.llm_response_browser, 3, 0, 1, 4)


        
        # 设置滑动条行为：滑动条在最下面时自动滚动到最新llm_response输出
        self.llm_response_browser.textChanged.connect(self.auto_scroll_llm_response)
        
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label, 4, 0, 1, 4)
        
        # 在窗口显示后调用防屏幕捕获设置（仅 Windows 有效）
        QTimer.singleShot(100, self.apply_screen_capture_protection)
    
    def auto_scroll_llm_response(self):
        cursor = self.llm_response_browser.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.llm_response_browser.setTextCursor(cursor)
        self.llm_response_browser.ensureCursorVisible()
    
    def apply_screen_capture_protection(self):
        if sys.platform.startswith("win"):
            prevent_screen_capture(self.winId())
    
    def start_recording(self):
        try:
            # 为每次录音生成唯一文件名
            filename = f"interview_{int(time.time())}.wav"
            #拼接MYCONFIG['DEFAULT']['OUTPUT_DIR']和filename
            filename = os.path.join(MYCONFIG['DEFAULT']['OUTPUT_DIR'],filename)
            print(f"开始录音: {filename}")
            self.recorder = LoopbackRecorder(device_index=MYCONFIG['DEFAULT'].getint('SPEAKER_DEVICE_INDEX'))
            device_info = self.recorder.device_info
            self.recording_thread = RecorderThread(self.recorder, filename)
            self.recording_thread.start()
            self.current_filename = filename
            self.status_label.setText(f"录音中... 设备为：({device_info['index']})({device_info['name']})")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        except Exception as e:
            print(f"启动录音失败: {e}")
            self.status_label.setText("录音启动失败")
    
    def stop_recording(self):
        try:
            self.recorder.is_recording = False
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            # 如果保存的文件大小为0，说明录音失败
            if os.path.getsize(self.current_filename) < 1:
                self.status_label.setText("录音失败：文件大小为0，可能是没有音频输入或输出")
                return
            self.recording_thread.join()
            self.status_label.setText("录音已停止")

            self.transcribe_btn.setEnabled(True)
            if self.auto_transcribe_chk.isChecked():
                self.transcribe_audio()

        except Exception as e:
            print(f"停止录音失败: {e}")
            self.status_label.setText("停止录音失败")

    
    def transcribe_audio(self):
        self.transcription_browser.clear()
        self.status_label.setText("转写中...")
        try:
            text = self.transcriber.transcribe(self.current_filename)
            self.transcription_browser.setPlainText(text)
            self.status_label.setText("转写完成")
            self.send_llm_btn.setEnabled(True)
            self.transcribe_btn.setEnabled(False)
            if self.auto_send_llm_chk.isChecked():
                self.send_to_llm()
        except Exception as e:
            print(f"转写失败: {e}")
            self.transcription_browser.setPlainText(f"转写失败: {e}\n")
    
    def send_to_llm(self):
        self.status_label.setText("LLM thinking...")
        self.llm_response_browser.clear()
        transcription = self.transcription_browser.toPlainText().strip()
        # 把DEFAULT_PROMPT拼接到转写的文本前面
        transcription = f"{self.default_prompt}\n{transcription}"
        if not transcription:
            self.llm_response_browser.setPlainText("转写文字为空，请先转写音频!\n")
            return
        threading.Thread(target=self.llm_thread, args=(transcription,), daemon=True).start()
    
    def llm_thread(self, text):
        # 回调函数：累积流式返回的文本，并用 markdown2 转换为 HTML 更新界面
        def update_ui(new_text):
            self.llm_full_text += new_text
            html = markdown2.markdown(self.llm_full_text)
            # 使用 QueuedConnection 确保线程安全更新
            QtCore.QMetaObject.invokeMethod(
                self.llm_response_browser, "setHtml", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, html)
            )
        
        try:
            # 在回复框中先显示第几次调用

            self.llm_client.get_response(text, callback=update_ui)
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(
                self.llm_response_browser, "append", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, f"\nLLM调用失败: {e}")
            )
        self.status_label.setText("LLM处理完成")
        # 更新调用次数并在回复框中显示，并绘制一个分割线（用markdown显示）
        divider = f"\n\n**第 {self.llm_client_ask_cnt} 次调用完成**\n\n---\n"
        self.llm_full_text += divider
        html = markdown2.markdown(self.llm_full_text)
        QtCore.QMetaObject.invokeMethod(
            self.llm_response_browser, "setHtml", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, html)
        )

        
        self.llm_client_ask_cnt += 1

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = InterviewAssistantGUI(MYCONFIG)
    window.show()
    sys.exit(app.exec_())
