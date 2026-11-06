from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import main
import transcription


@pytest.fixture(autouse=True)
def remove_test_database():
    yield
    Path("test_teleprompter.db").unlink(missing_ok=True)


def test_transcribe_audio_uses_local_model(monkeypatch):
    received: dict[str, object] = {}

    def fake_transcribe(contents: bytes, suffix: str) -> str:
        received["contents"] = contents
        received["suffix"] = suffix
        return "Texto reconhecido."

    monkeypatch.setattr(main, "transcribe_audio_bytes", fake_transcribe)
    monkeypatch.setattr(main, "MODEL_NAME", "test-model")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/transcriptions",
            files={"audio": ("gravacao.wav", b"audio-content", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "Texto reconhecido.",
        "model": "faster-whisper:test-model",
    }
    assert received == {"contents": b"audio-content", "suffix": ".wav"}


def test_transcription_is_independent_of_openai_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "transcribe_audio_bytes", lambda *_args: "Texto local.")
    with TestClient(main.app) as client:
        response = client.post(
            "/api/transcriptions",
            files={"audio": ("gravacao.wav", b"audio-content", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "Texto local."


def test_transcription_rejects_unsupported_audio_format():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/transcriptions",
            files={"audio": ("gravacao.ogg", b"audio-content", "audio/ogg")},
        )

    assert response.status_code == 415


def test_transcription_rejects_audio_over_25_mb():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/transcriptions",
            files={
                "audio": (
                    "gravacao.wav",
                    b"a" * (25 * 1024 * 1024 + 1),
                    "audio/wav",
                )
            },
        )

    assert response.status_code == 413


def test_realtime_transcription_processes_pcm_locally(monkeypatch):
    received: list[bytes] = []

    def fake_transcribe(contents: bytes) -> str:
        received.append(contents)
        return "Texto reconhecido ao vivo."

    monkeypatch.setattr(main, "transcribe_pcm16_bytes", fake_transcribe)
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/integration-test/transcription") as websocket:
            ready = websocket.receive_json()
            websocket.send_json(
                {"type": "input_audio_buffer.append", "audio": "AQACAAMA"}
            )
            websocket.send_json({"type": "input_audio_buffer.commit"})
            committed = websocket.receive_json()
            started = websocket.receive_json()
            delta = websocket.receive_json()
            completed = websocket.receive_json()

    assert ready["type"] == "session.updated"
    assert committed["type"] == "input_audio_buffer.committed"
    assert started["type"] == "transcription.started"
    assert delta == {
        "type": "conversation.item.input_audio_transcription.delta",
        "item_id": committed["item_id"],
        "delta": "Texto reconhecido ao vivo.",
    }
    assert completed == {
        "type": "conversation.item.input_audio_transcription.completed",
        "item_id": committed["item_id"],
        "transcript": "Texto reconhecido ao vivo.",
    }
    assert received == [b"\x01\x00\x02\x00\x03\x00"]


def test_pcm_audio_is_decodable_by_faster_whisper_audio_backend(monkeypatch):
    from faster_whisper.audio import decode_audio

    decoded_samples: list[int] = []

    def decode_written_wav(path: str | Path) -> str:
        decoded_samples.extend(decode_audio(str(path), sampling_rate=24_000).tolist())
        return "decoded"

    monkeypatch.setattr(transcription, "transcribe_file", decode_written_wav)
    result = transcription.transcribe_pcm16_bytes(b"\x00\x00" * 2_400)

    assert result == "decoded"
    assert len(decoded_samples) == 2_400
