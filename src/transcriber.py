# 第一次运行会自动下载模型文件
import whisper
from whisper.utils import get_writer
import os
import configparser

#获取当前文件的绝对路径，向上一级，用绝对路径找到config.ini并读取
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
config_path = os.path.join(project_root, 'config.ini')
MYCONFIG = configparser.ConfigParser()
MYCONFIG.read(config_path,encoding='utf-8')


class SpeechTranscriber:
    def __init__(self, model_size=MYCONFIG['DEFAULT']['WHISPER_MODEL_SIZW']):
        self.model = whisper.load_model(model_size)
        
    def transcribe(self, audio_path):
        #判断这个音频文件大小是否小于1个字节
        if os.path.getsize(audio_path) < 1:
            return "音频文件大小为0"
        result = self.model.transcribe(audio_path)
        return result["text"]

if __name__ == "__main__":
    transcriber = SpeechTranscriber()
    text = transcriber.transcribe("output/test_record.wav")
    print("转写结果:", text)
