from src.audio_capture import LoopbackRecorder
from src.transcriber import SpeechTranscriber
from src.llm_client import LLMClient
import time
import os

def update_response(new_text):
    #作为回调函数，更新response
    print(new_text, end="", flush=True,sep="")

def main():
    while True:
        # 1. 录音
        # 按ctrl+c开始
        client = LLMClient()
        input('按任意键开始录音...')
        # 开始录音
        print("正在启动录音...")
        recorder = LoopbackRecorder(device_index=33)
        recorder.start_recording("interview.wav")
        recorder.record(duration=5)# 录制5秒

        recorder.stop_recording()
        print("录音完成")

        # 2. 转写
        print("\n开始转写...")
        transcriber = SpeechTranscriber()
        text = transcriber.transcribe("interview.wav")
        print(f"\n转写内容: {text}")
        
        # 3. LLM处理
        
        print("\n模型回复:")
        full_response = []
        client.get_response(f"\n{text}", callback=update_response)


if __name__ == "__main__":
    main()