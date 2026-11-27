"""Libra TTS: a 0.3B-parameter multilingual text-to-speech model (16 languages, 8 voices, 24 kHz)."""
from .api import LibraTTS
from .config import Sampling

__all__ = ["LibraTTS", "Sampling"]
__version__ = "0.1.0"
