# InterPilot

English | [中文](README.md)

InterPilot is a Windows desktop assistant for paper presentations, meetings, and Q&A. It captures microphone and system-loopback audio as separate sources, transcribes the discussion, and combines recent speech with a slide screenshot and paper excerpts to produce concise, source-aware speaking notes.

Users are responsible for ensuring that recording, transcription, and data upload comply with meeting rules, participant consent requirements, and local law. Use headphones and keep unrelated notifications and media off the selected output device.

## Features

- Independent microphone and WASAPI loopback selection, enable switches, and level meters.
- Local Whisper or SiliconFlow cloud transcription with silence-aware chunking; local mode shows rolling drafts and corrects them after a pause.
- Semi-automatic mode: keep transcribing and request a hint with a button or global hotkey.
- Automatic mode: check new discussion for questions or objections and stay quiet when no useful hint is needed.
- Local PDF text extraction and page-level excerpts with physical PDF page references.
- A preselected monitor can be captured directly by hotkey, with manual region selection available as an option.
- One Settings window covers the API, model, prompts, audio devices, paper, initial image, screenshot strategy, and hotkeys. Both SiliconFlow and local OpenAI-compatible endpoints are supported.
- Available models can be fetched, searched, and selected from a dropdown. Thinking is disabled by default for low first-token latency, with an optional token budget.
- The API key is optional for local services. Remote keys can be stored with Windows DPAPI and are never written to JSON or Git.
- Streaming output, connection reuse, first-token/total latency display, cancellation, session export, and page pinning.
- The answer pane receives most of the window by default; Focus mode hides the sidebar and transcript when needed.
- Focus mode can keep the transcript visible, while rolling ASR text remains at a fixed UI height.
- Optional always-on-top mode for reading hints above the presentation window.

The default answer/vision model is `Qwen/Qwen3.8-27B`. Actual model access depends on the account. Use Settings to test the connection, refresh the model list, or enter a model ID directly.

![InterPilot presentation console](doc_pic/GUI.png)

## Presentation workflow

1. Wear headphones, silence notifications, and make sure the chosen output device mainly carries the online meeting.
2. In Settings, select the paper PDF, microphone, and loopback device for the headphones in use.
3. Select the monitor that will share the slides and use full-screen capture.
4. Start in semi-automatic mode and press `Ctrl+Alt+Enter` when you want a hint.
5. After changing slides, press `Ctrl+Alt+S` to capture the configured monitor and request a hint.
6. Enable automatic mode after the device and prompt behavior have been validated.

A clear screenshot is enough to test the visual Q&A path. It remains fixed until the capture hotkey replaces it.

## Default global hotkeys

| Action | Hotkey |
| --- | --- |
| Start / pause listening | `Ctrl+Alt+R` |
| Request a hint | `Ctrl+Alt+Enter` |
| Capture the configured monitor and request | `Ctrl+Alt+S` |
| Show / hide the window | `Ctrl+Alt+H` |

## Install and run

Python 3.10 is recommended:

```powershell
conda create -n interpilot python=3.10
conda activate interpilot
pip install -r requirements.txt
python main.py
```

Local Whisper also requires FFmpeg. On Windows with Scoop:

```powershell
scoop install ffmpeg
```

Open Settings on first launch, enter the API URL and model ID, and add an API key only when the service requires one. Fetch the model list to test the connection, then select the transcription mode and models. Settings are stored in the Git-ignored `config.local.json`; an optionally remembered key is encrypted for the current Windows account in `config.key`. Do not place a real key in `config.ini`.

### Local OpenAI-compatible endpoints

Any local server that implements an OpenAI-compatible Chat Completions endpoint can be used without a key:

```text
API URL:  http://localhost:8000/v1
API key:  leave blank
Model ID: use the name exposed by the local server
```

Include the `/v1` path expected by the server. The model dropdown depends on `GET /models`; if the server does not implement it, enter the model ID manually. Screenshot requests also require a model and server that accept OpenAI-style image input. Clear the initial reference image and avoid “Capture & Ask” when using a text-only model.

## Data handling

- Local Whisper keeps transcription on the computer and deletes temporary WAV chunks after processing.
- Cloud ASR uploads audio chunks to the configured service.
- Hint requests send recent discussion, selected paper excerpts, and the current screenshot to the answer model.
- The PDF is parsed locally; only selected excerpts are included in requests.
- Exported sessions may contain meeting content and should be stored appropriately.

Source labels describe capture channels rather than verified speaker identities.

## Diagnostics and tests

```powershell
python main_cmd.py --list-devices
python main_cmd.py --audio output/test_record.wav --transcribe-only
pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q main.py main_cmd.py src
python -m ruff check main.py main_cmd.py src tests
```

Example paper/slide request:

```powershell
python main_cmd.py --paper pre/paper.pdf --image pre/slide.png --question "Explain the roles of the two stages on this slide"
```

Hardware capture still requires one manual test with the actual headset and microphone.

## Current limitations

- Local lexical page retrieval is designed for short papers; longer corpora would benefit from a vector index.
- References use physical PDF pages, which can differ from printed journal page numbers.
- Scanned PDFs need OCR first.
- Automatic hints can still false-trigger and should be calibrated before a live presentation.
- Screenshots do not update automatically when slides change.
- Rolling transcription drafts reduce visible latency but may change; only corrected final segments trigger automatic hint checks.
- The first version relies on the user to keep unrelated system sounds off the selected output device.

## License

Licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) for non-commercial use only.
