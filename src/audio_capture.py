"""Independent WASAPI / microphone streams, bounded queues, silence chunking."""
import math
import queue
import tempfile
import threading
import time
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from src.context import Transcript
from src.llm_client import safe_error
from src.settings import ROOT
from src.transcriber import SpeechTranscriber


def list_devices():
    import pyaudiowpatch as pa
    with pa.PyAudio() as audio:
        devices = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if info["maxInputChannels"] > 0:
                devices.append(dict(info))
        return devices


def rms(data):
    samples = array("h", data)
    return math.sqrt(sum(float(x) * x for x in samples) / len(samples)) if samples else 0


class Chunker:
    """PCM16 chunks ending at silence or maximum duration, with short pre-roll."""
    def __init__(self, rate, channels, settings):
        self.rate, self.channels, self.settings = rate, channels, settings
        self.frames = []
        self.duration = self.quiet = self.voiced = 0.0
        self.last_partial = 0.0
        self.started = None
        self.pre_roll = b""

    def push(self, data, timestamp):
        duration = len(data) / (2 * self.rate * self.channels)
        volume = rms(data)
        voiced = volume >= self.settings.energy_threshold
        if not self.frames and not voiced:
            self.pre_roll = data
            return None, volume
        if not self.frames:
            self.started = timestamp - len(self.pre_roll) / (2 * self.rate * self.channels)
            if self.pre_roll:
                self.frames.append(self.pre_roll)
            self.pre_roll = b""
        self.frames.append(data)
        self.duration += duration
        self.voiced += duration if voiced else 0
        self.quiet = 0 if voiced else self.quiet + duration
        if (self.duration >= self.settings.chunk_seconds or
                self.quiet >= self.settings.silence_ms / 1000):
            return self.flush(), volume
        return None, volume

    def partial(self):
        interval = self.settings.partial_interval_ms / 1000
        if (not self.frames or self.voiced < .2 or
                self.duration - self.last_partial < interval):
            return None
        self.last_partial = self.duration
        return b"".join(self.frames), self.started

    def flush(self):
        result = (b"".join(self.frames), self.started) if self.voiced >= .2 else None
        self.frames = []
        self.duration = self.quiet = self.voiced = self.last_partial = 0.0
        self.started = None
        return result


@dataclass
class Segment:
    path: Path
    source: str
    timestamp: float
    final: bool = True


class AudioSession:
    """One capture owner and one sequential ASR worker. UI only sees events."""
    def __init__(self, settings, emit):
        self.settings, self.emit = settings, emit
        self.stop_event = threading.Event()
        self.closed = threading.Event()
        self.capture_done = threading.Event()
        self.pending = queue.Queue(maxsize=8)
        self.partial_latest = {}
        self.partial_lock = threading.Lock()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="audio-session")
        self.thread.start()

    def stop(self, discard=False):
        if discard:
            self.closed.set()
        self.stop_event.set()

    def _save(self, chunk, source, rate, channels, final=True):
        if not chunk or self.closed.is_set():
            return
        directory = ROOT / "output" / "chunks"
        directory.mkdir(parents=True, exist_ok=True)
        data, timestamp = chunk
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=directory, delete=False) as temp:
            path = Path(temp.name)
        with wave.open(str(path), "wb") as target:
            target.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
            target.writeframes(data)
        segment = Segment(path, source, timestamp, final)
        if not final:
            with self.partial_lock:
                previous = self.partial_latest.get(source)
                self.partial_latest[source] = segment
            if previous:
                previous.path.unlink(missing_ok=True)
            return
        with self.partial_lock:
            previous = self.partial_latest.pop(source, None)
        if previous:
            previous.path.unlink(missing_ok=True)
        try:
            self.pending.put_nowait(segment)
        except queue.Full:
            path.unlink(missing_ok=True)
            self.emit("warning", "转写跟不上录音，已丢弃新片段；请选更快的转写模型或增加分段时长。")

    def _take_partial(self):
        with self.partial_lock:
            if not self.partial_latest:
                return None
            source = next(iter(self.partial_latest))
            return self.partial_latest.pop(source)

    def _has_partial(self):
        with self.partial_lock:
            return bool(self.partial_latest)

    def _transcribe(self):
        transcriber = SpeechTranscriber(settings=self.settings)
        if self.settings.asr_backend == "local":
            try:
                self.emit("asr_status", f"正在准备 Whisper {self.settings.whisper_model}…")
                transcriber.preload()
                self.emit("asr_status", "Whisper 已就绪 · 正在实时监听")
            except Exception as exc:
                self.emit("warning", "Whisper 加载失败：" + safe_error(exc, self.settings.api_key))
        while (not self.capture_done.is_set() or not self.pending.empty() or
               self._has_partial()):
            final_queue_item = False
            try:
                segment = self.pending.get_nowait()
                final_queue_item = True
            except queue.Empty:
                segment = self._take_partial()
                if segment is None:
                    time.sleep(.05)
                    continue
            try:
                if not self.closed.is_set():
                    if segment.final:
                        self.emit("asr_status", f"正在校正 {segment.source} · 待处理 {self.pending.qsize()} 段")
                    text = transcriber.transcribe(segment.path)
                    if text and not self.closed.is_set():
                        if segment.final:
                            self.emit("transcript", Transcript(segment.source, segment.timestamp, text))
                        else:
                            self.emit("partial", (segment.source, segment.timestamp, text))
            except Exception as exc:
                self.emit("warning", "转写失败：" + safe_error(exc, self.settings.api_key))
            finally:
                segment.path.unlink(missing_ok=True)
                if final_queue_item:
                    self.pending.task_done()

    def _run(self):
        import pyaudiowpatch as pa
        audio = None
        streams, chunkers = [], {}
        raw = queue.Queue(maxsize=256)
        overflow = threading.Event()
        worker = threading.Thread(target=self._transcribe, daemon=True, name="transcription")
        worker.start()
        try:
            audio = pa.PyAudio()
            sources = []
            if self.settings.mic_enabled:
                sources.append(("麦克风", self.settings.mic_device, False))
            if self.settings.system_enabled:
                sources.append(("系统声音", self.settings.system_device, True))
            if not sources:
                raise ValueError("请至少勾选一路声音")
            for source, index, loopback in sources:
                if index < 0:
                    info = (audio.get_default_wasapi_loopback() if loopback
                            else audio.get_default_input_device_info())
                else:
                    info = audio.get_device_info_by_index(index)
                if bool(info.get("isLoopbackDevice", False)) != loopback:
                    raise ValueError(f"{source}设备类型已改变，请刷新并重新选择设备")
                rate, channels = int(info["defaultSampleRate"]), int(info["maxInputChannels"])
                if channels < 1:
                    raise ValueError(f"{source}没有输入通道")
                chunkers[source] = Chunker(rate, channels, self.settings)

                def callback(data, count, timing, status, source=source, rate=rate):
                    if status:
                        overflow.set()
                    try:
                        raw.put_nowait((source, data, time.time() - count / rate))
                    except queue.Full:
                        overflow.set()
                    return None, pa.paContinue

                streams.append(audio.open(format=pa.paInt16, channels=channels, rate=rate,
                    input=True, input_device_index=int(info["index"]),
                    frames_per_buffer=1024, stream_callback=callback))
            self.emit("capture_started", None)
            last_levels = {}
            while not self.stop_event.is_set():
                if any(not stream.is_active() for stream in streams):
                    raise RuntimeError("录音设备已停止，请检查设备连接后重新开始")
                try:
                    source, data, timestamp = raw.get(timeout=.1)
                except queue.Empty:
                    continue
                chunker = chunkers[source]
                chunk, level = chunker.push(data, timestamp)
                if time.monotonic() - last_levels.get(source, 0) > .15:
                    self.emit("level", (source, min(100, int(level / 32768 * 500))))
                    last_levels[source] = time.monotonic()
                self._save(chunk, source, chunker.rate, chunker.channels, final=True)
                if (not chunk and self.settings.live_partial_enabled and
                        self.settings.asr_backend == "local"):
                    self._save(chunker.partial(), source, chunker.rate,
                               chunker.channels, final=False)
                if overflow.is_set():
                    self.emit("warning", "录音缓冲区溢出，部分音频可能丢失。")
                    overflow.clear()
        except Exception as exc:
            if isinstance(exc, OSError):
                detail = "所选设备目前不可用。请确认耳机/麦克风已连接，关闭独占该设备的程序，然后刷新并重新选择设备。"
            else:
                detail = safe_error(exc, self.settings.api_key)
            self.emit("warning", "录音失败：" + detail)
        finally:
            for stream in streams:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if audio:
                audio.terminate()
            while not raw.empty():
                source, data, timestamp = raw.get_nowait()
                chunker = chunkers[source]
                chunk, _ = chunker.push(data, timestamp)
                self._save(chunk, source, chunker.rate, chunker.channels)
            for source, chunker in chunkers.items():
                self._save(chunker.flush(), source, chunker.rate, chunker.channels)
            self.capture_done.set()
            self.emit("capture_stopped", None)
            worker.join()
            self.emit("session_done", None)


if __name__ == "__main__":
    for device in list_devices():
        print(device["index"], device["name"], "loopback" if device.get("isLoopbackDevice") else "input")
