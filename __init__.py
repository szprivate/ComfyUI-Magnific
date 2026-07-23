"""ComfyUI-Magnific — ComfyUI nodes wrapping the Magnific / Freepik AI REST API.

Nodes (category "Magnific"):
  * MagnificImageGenerate  — text-to-image (Mystic)
  * MagnificUpscale        — creative & precise upscaling
  * MagnificVideoGenerate  — text-to-video & image-to-video (Kling, Veo, Seedance, ...)
  * MagnificReferenceCreate — Soul-style character/style reference packaging
  * MagnificTTS            — text-to-speech (ElevenLabs voiceover)

Auth: node 'api_key' widget, else MAGNIFIC_API_KEY / FREEPIK_API_KEY env var,
else a *_api_key.txt file next to this pack.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
