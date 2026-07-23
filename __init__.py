"""ComfyUI-Magnific — ComfyUI nodes wrapping the Magnific / Freepik AI REST API.

Nodes (category "Magnific"):
  * MagnificImageGenerate  — text-to-image (Mystic)
  * MagnificTextToImage    — text-to-image (Flux, Seedream, Z-Image, Hyperflux, Runway)
  * MagnificImageEdit      — style transfer, Kontext edit, relight, remove bg, expand, ...
  * MagnificUpscale        — creative & precise upscaling
  * MagnificVideoGenerate  — image/text-to-video (Kling 2.x, Seedance, Hailuo, Wan, ...)
  * MagnificVideoAdvanced  — Kling 3 / Omni, OmniHuman, Act-Two, VFX (/v1/ai/video/)
  * MagnificReferenceCreate — Soul-style character/style reference packaging
  * MagnificTTS            — text-to-speech (ElevenLabs voiceover)
  * MagnificAudioGenerate  — music & sound effects
  * MagnificAudioIsolation — isolate a described sound from audio/video

Auth: node 'api_key' widget, else MAGNIFIC_API_KEY / FREEPIK_API_KEY env var,
else a *_api_key.txt file next to this pack.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
