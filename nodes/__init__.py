"""Aggregate the node class + display-name mappings from every node module."""
from __future__ import annotations

from . import (
    audio,
    image_edit,
    image_generate,
    reference,
    text_to_image,
    tts,
    upscale,
    video_advanced,
    video_generate,
)

NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

for _mod in (image_generate, text_to_image, image_edit, upscale, video_generate,
             video_advanced, reference, tts, audio):
    NODE_CLASS_MAPPINGS.update(_mod.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_mod.NODE_DISPLAY_NAME_MAPPINGS)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
