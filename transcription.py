from __future__ import annotations

import os
import tempfile
import threading
import wave
from pathlib import Path

from faster_whisper import WhisperModel

MODEL_NAME = os.getenv("FASTER_WHISPER_MODEL", "small")
SAMPLE_RATE = 24_000
MAX_PCM_DURATION_SECONDS = 30

_model: WhisperModel | None = None
_model_lock = threading.Lock()
_transcription_lock = threading.Lock()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(
                    MODEL_NAME,
                    device="cpu",
                    compute_type="int8",
                )
    return _model


def transcribe_file(path: str | Path) -> str:
    with _transcription_lock:
        model = _get_model()
        segments, _ = model.transcribe(
            str(path),
            language="pt",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def transcribe_audio_bytes(contents: bytes, suffix: str) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / f"audio{suffix}"
        audio_path.write_bytes(contents)
        return transcribe_file(audio_path)


def transcribe_pcm16_bytes(contents: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    if len(contents) % 2:
        raise ValueError("O áudio PCM precisa conter amostras de 16 bits completas.")
    if len(contents) > sample_rate * 2 * MAX_PCM_DURATION_SECONDS:
        raise ValueError("O trecho de áudio excede o limite de 30 segundos.")

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = Path(temp_dir) / "audio.wav"
        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(contents)
        return transcribe_file(audio_path)
