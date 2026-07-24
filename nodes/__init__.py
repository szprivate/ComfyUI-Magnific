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

# The MCP node is optional (OAuth + the `mcp` package) and is a V3-schema node
# (comfy_api.latest.io) — it needs ComfyUI's runtime to import. Register it
# defensively so a missing dep or import hiccup never takes down the REST nodes.
# Finalize its schema at load (mirroring the comfy_entrypoint path) so it registers
# cleanly through the classic NODE_CLASS_MAPPINGS route alongside the V1 nodes.
try:
    from . import mcp_video
    for _cls in mcp_video.NODE_CLASS_MAPPINGS.values():
        if hasattr(_cls, "GET_SCHEMA"):
            _cls.GET_SCHEMA()  # validate + finalize the V3 schema
    NODE_CLASS_MAPPINGS.update(mcp_video.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(mcp_video.NODE_DISPLAY_NAME_MAPPINGS)
except Exception as _exc:  # noqa: BLE001
    print(f"[ComfyUI-Magnific] MCP video node not loaded ({_exc}); REST nodes unaffected.")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
