import edge_tts
import pyaudiowpatch as pyaudio
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional, Callable

@dataclass
class TTSConfig:
    voice: str = "zh-TW-HsiaoYuNeural"
    sample_rate: int = 24000
    channels: int = 1
    format: int = pyaudio.paInt16

class VoiceGenerator:
    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or TTSConfig()
        self.p = pyaudio.PyAudio()
        self._stop_event = threading.Event()
        self._current_stream = None

    def _create_ffmpeg_process(self):
        return subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ac", str(self.config.channels),
                "-ar", str(self.config.sample_rate),
                "pipe:1"
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )

    def _audio_output_thread(self, ffmpeg_process):
        stream = self.p.open(
            format=self.config.format,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            output=True
        )
        self._current_stream = stream
        
        try:
            while not self._stop_event.is_set():
                data = ffmpeg_process.stdout.read(1024)
                if not data:
                    break
                stream.write(data)
        finally:
            stream.stop_stream()
            stream.close()
            self.p.terminate()

    def speak(self, text: str, callback: Optional[Callable] = None):
        """非阻塞式播放"""
        self._stop_event.clear()
        
        def _run():
            try:
                communicate = edge_tts.Communicate(text, voice=self.config.voice)
                ffmpeg_process = self._create_ffmpeg_process()
                
                audio_thread = threading.Thread(
                    target=self._audio_output_thread, 
                    args=(ffmpeg_process,)
                )
                audio_thread.start()

                for chunk in communicate.stream_sync():
                    if chunk["type"] == "audio":
                        ffmpeg_process.stdin.write(chunk["data"])
                
                ffmpeg_process.stdin.close()
                audio_thread.join()
                ffmpeg_process.wait()
                
                if callback:
                    callback(True, None)
            except Exception as e:
                if callback:
                    callback(False, str(e))
            finally:
                self._current_stream = None

        threading.Thread(target=_run).start()

    def stop(self):
        """立即停止播放"""
        self._stop_event.set()
        if self._current_stream:
            self._current_stream.stop_stream()

if __name__ == "__main__":
    generator = VoiceGenerator()
    generator.speak("你好，欢迎使用Edge TTS。")
    input("按回车键停止播放...")
    generator.stop()
# Compare this snippet from util.py:
