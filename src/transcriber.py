"""Lazy ASR: no model import or download on GUI startup."""
import threading
from pathlib import Path
from src.settings import Settings


class SpeechTranscriber:
    _models = {}
    _locks = {}
    _guard = threading.Lock()

    def __init__(self, model_size=None, settings=None):
        self.settings = settings or Settings()
        self.model_size = model_size or self.settings.whisper_model

    def preload(self):
        if self.settings.asr_backend == "local":
            self._local_model(self.model_size)

    @classmethod
    def _local_model(cls, model_size):
        with cls._guard:
            lock = cls._locks.setdefault(model_size, threading.Lock())
        with lock:
            if model_size not in cls._models:
                import whisper
                cls._models[model_size] = whisper.load_model(model_size)
            return cls._models[model_size], lock

    def transcribe(self, audio_path):
        if Path(audio_path).stat().st_size <= 44:
            return ""
        if self.settings.asr_backend == "cloud":
            from openai import OpenAI
            with OpenAI(api_key=self.settings.api_key or "not-required",
                        base_url=self.settings.api_url,
                        timeout=self.settings.timeout, max_retries=0) as client:
                with open(audio_path, "rb") as source:
                    result = client.audio.transcriptions.create(
                        model=self.settings.asr_model, file=source)
                return result.text.strip()
        model, lock = self._local_model(self.model_size)
        options = {"fp16": str(model.device).startswith("cuda"),
                   "condition_on_previous_text": False}
        if self.settings.language != "auto":
            options["language"] = self.settings.language
        with lock:
            return model.transcribe(str(audio_path), **options)["text"].strip()
