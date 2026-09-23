import json
import threading
from array import array
from types import SimpleNamespace

import pytest
import src.llm_client as llm_module

from src.audio_capture import Chunker
from src.context import Paper, build_prompt
from src.hotkeys import parse_hotkey
from src.llm_client import LLMClient, image_content
from src.settings import Settings, load_secret, save_secret


def test_local_openai_endpoint_uses_placeholder_key(monkeypatch):
    captured = {}

    class ConstructorClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "OpenAI", ConstructorClient)
    settings = Settings(api_url="http://localhost:8000/v1", api_key="")
    LLMClient(settings=settings)
    assert captured["api_key"] == "not-required"
    assert captured["base_url"] == "http://localhost:8000/v1"


def test_settings_never_write_plaintext_key(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(api_key="super-secret", remember_api_key=False)
    settings.save(path)
    raw = path.read_text(encoding="utf-8")
    assert "super-secret" not in raw
    assert "api_key" not in json.loads(raw)


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows DPAPI")
def test_dpapi_roundtrip(tmp_path):
    path = tmp_path / "secret.bin"
    save_secret("test-secret-中文", path)
    assert path.read_bytes() != b"test-secret-\xe4\xb8\xad\xe6\x96\x87"
    assert load_secret(path) == "test-secret-中文"


def test_hotkey_parser_and_validation():
    assert parse_hotkey("Ctrl+Alt+R")[1] == ord("R")
    assert parse_hotkey("Shift+F12")[1] == 123
    with pytest.raises(ValueError):
        parse_hotkey("R")
    with pytest.raises(ValueError):
        parse_hotkey("Ctrl+Banana")


def test_chunker_flushes_on_silence():
    settings = Settings(chunk_seconds=2, silence_ms=500, energy_threshold=100)
    chunker = Chunker(1000, 1, settings)
    voiced = array("h", [1000] * 300).tobytes()
    quiet = array("h", [0] * 600).tobytes()
    assert chunker.push(voiced, 10)[0] is None
    chunk, level = chunker.push(quiet, 10.3)
    assert chunk is not None
    data, timestamp = chunk
    assert data.startswith(voiced)
    assert timestamp == pytest.approx(10)
    assert level == 0


def test_chunker_emits_replaceable_partial_before_final():
    settings = Settings(chunk_seconds=6, silence_ms=500, energy_threshold=100,
                        partial_interval_ms=500)
    chunker = Chunker(1000, 1, settings)
    voiced = array("h", [1000] * 600).tobytes()
    assert chunker.push(voiced, 20)[0] is None
    partial = chunker.partial()
    assert partial is not None
    data, timestamp = partial
    assert data == voiced
    assert timestamp == pytest.approx(20)
    assert chunker.partial() is None


def test_paper_retrieval_keeps_physical_page_labels():
    paper = Paper("paper.pdf", ["intro", "method bridge stage two", "results"])
    result = paper.excerpts("stage two", budget=1000)
    assert "paper.pdf | PDF 第 2 页" in result
    assert "method bridge stage two" in result


def test_prompt_preserves_sources_and_untrusted_boundaries():
    settings = Settings(user_prompt="给出提示")
    paper = Paper("paper.pdf", ["method"])
    prompt = build_prompt(settings, "[12:00 · 系统声音] why?", paper, 1, True, "slide.png")
    assert "<discussion>" in prompt and "</discussion>" in prompt
    assert "<reference>" in prompt and "PDF 第 1 页" in prompt
    assert "[NO_HINT]" in prompt
    assert "slide.png" in prompt


class FakeStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content=None, reasoning_content="internal reasoning"))])
        for text in ["hello", None, " world"]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=text, reasoning_content=None))])

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self):
        self.stream = FakeStream()
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream

    def close(self):
        pass


def test_llm_uses_separate_system_message_and_image():
    fake = FakeClient()
    settings = Settings(system_prompt="system", max_tokens=321)
    client = LLMClient(settings=settings, client=fake)
    pieces = []
    activity = []
    answer = client.get_response("question", callback=pieces.append, image=b"png",
                                 activity_callback=lambda: activity.append(True))
    assert answer == "hello world"
    assert pieces == ["hello", " world"]
    assert activity == [True]
    assert fake.kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert fake.kwargs["messages"][1]["content"][0] == image_content(b"png")
    assert fake.kwargs["messages"][1]["content"][1]["type"] == "text"
    assert fake.kwargs["max_tokens"] == 321
    assert fake.kwargs["extra_body"] == {"enable_thinking": False}
    assert fake.stream.closed


def test_llm_cancel_before_request():
    fake = FakeClient()
    cancel = threading.Event()
    cancel.set()
    client = LLMClient(settings=Settings(), client=fake)
    assert client.get_response("question", cancel=cancel) == ""
    assert fake.kwargs is None


def test_llm_can_bound_optional_thinking():
    fake = FakeClient()
    settings = Settings(enable_thinking=True, thinking_budget=256)
    client = LLMClient(settings=settings, client=fake)
    client.get_response("question")
    assert fake.kwargs["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 256,
    }
