"""MagnificMCPVideo — reach the newer video models via the Magnific MCP.

The REST API (the other nodes) only exposes a curated subset of models. This node
talks to the Magnific **MCP** (`mcp.magnific.com`, OAuth), whose generic
`video_generate` takes a model **slug** from a much larger, more current catalog —
Seedance 2.0, Sora 2, Veo 3.1, Kling 3, etc.

This is a ComfyUI **V3-schema** node (`comfy_api.latest.io`) so it can use a native
**autogrow** input group for references: connect one reference image and the next
empty slot appears, letting you fan in multiple reference images. Reference videos
and audio are given as URLs / creation identifiers.

Auth: the node signs you in on demand — the first run (with no stored token) opens
your browser to authorize Magnific, then proceeds to generate; the token is reused
silently afterwards. `mcp` must be installed in ComfyUI's Python (`pip install mcp`).
(`authorize_magnific.py` can still pre-authorize from a terminal if you prefer.)

Image inputs are uploaded to the MCP (request_upload -> PUT -> finalize); URLs are
used as-is (a URL wins over a connected IMAGE for the same slot).
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import os

from comfy_api.latest import io, InputImpl, ui

# Import the pack-root mcp_client / freepik_api whether loaded as a package or not.
_PACK_DIR = Path(__file__).resolve().parent.parent
if str(_PACK_DIR) not in sys.path:
    sys.path.insert(0, str(_PACK_DIR))

import mcp_client  # noqa: E402
from freepik_api import tensor_to_base64_png  # noqa: E402


def _png_bytes(image) -> bytes:
    """A ComfyUI IMAGE tensor (single frame) -> raw PNG bytes."""
    return base64.b64decode(tensor_to_base64_png(image))


# Model slugs from the MCP video_models_list catalog (newer / REST-missing ones).
# "custom" -> use the slug_override widget for anything not listed here.
MODEL_SLUGS = [
    "bytedance-seedance-pro-2.0",
    "bytedance-seedance-fast-2.0",
    "bytedance-seedance-mini-2.0",
    "bytedance-seedance-pro-1.5",
    "kling-30",
    "kling-omni3",
    "kling-30-turbo",
    "openai-sora2-standard",
    "openai-sora2-pro",
    "google-veo3_1",
    "google-veo3_1-fast",
    "custom",
]
ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]
RESOLUTIONS = ["1080p", "720p", "580p", "480p"]
# Reference roles the MCP references array accepts (per-model support varies).
REFERENCE_IMAGE_TYPES = ["image", "character", "style", "product", "effect"]
_MAX_REFERENCE_IMAGES = 8


class MagnificMCPVideo(io.ComfyNode):
    """Generate video through the Magnific MCP (Seedance 2.0, Sora 2, Kling 3, ...)
    with multiple reference images/videos."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MagnificMCPVideo",
            display_name="Magnific MCP Video (Seedance 2.0 / Sora 2 / Kling 3)",
            category="Magnific",
            description="Newer Magnific video models via the MCP, with autogrow "
                        "reference images + reference video/audio URLs.",
            is_output_node=True,
            inputs=[
                io.Combo.Input("model", options=MODEL_SLUGS, default="bytedance-seedance-pro-2.0"),
                io.String.Input("prompt", multiline=True, default="",
                                tooltip="Text prompt (required unless a start image is given)."),
                io.Int.Input("duration", default=5, min=1, max=30,
                             tooltip="Seconds (allowed range per model)."),
                io.Combo.Input("aspect_ratio", options=ASPECT_RATIOS, default="16:9"),
                io.Combo.Input("resolution", options=RESOLUTIONS, default="1080p"),
                io.String.Input("slug_override", optional=True, default="",
                                tooltip="Exact slug from video_models_list; used when model=custom."),
                # Image-to-video keyframes.
                io.Image.Input("start_image", optional=True,
                               tooltip="Keyframe start (uploaded to the MCP)."),
                io.Image.Input("end_image", optional=True, tooltip="Keyframe end (optional)."),
                io.String.Input("start_image_url", optional=True, default="",
                                tooltip="Public URL / creation id; overrides start_image."),
                io.String.Input("end_image_url", optional=True, default=""),
                # Autogrow reference images — connect one, another slot appears.
                io.Autogrow.Input(
                    "reference_images", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input("reference_image",
                                             tooltip="Reference image (uploaded to the MCP)."),
                        prefix="reference_image_", min=0, max=_MAX_REFERENCE_IMAGES),
                    tooltip="Multiple reference images — each connection grows a new slot."),
                io.Combo.Input("reference_image_type", options=REFERENCE_IMAGE_TYPES, default="image",
                               optional=True, tooltip="Role applied to the reference images above."),
                io.String.Input("reference_video_urls", optional=True, multiline=True, default="",
                                tooltip="Reference video URLs / creation ids — one per line."),
                io.String.Input("reference_audio_url", optional=True, default="",
                                tooltip="Reference audio URL (Seedance 2.0 lipsync)."),
                io.String.Input("extra_params_json", optional=True, multiline=True, default="",
                                tooltip="Merged into the clip, e.g. {\"withSoundEffects\": true}."),
                io.Float.Input("poll_interval", optional=True, default=6.0, min=2.0, max=60.0, step=1.0),
                io.Int.Input("max_wait_seconds", optional=True, default=1800, min=60, max=3600, step=30),
            ],
            outputs=[
                io.Video.Output(display_name="video"),
                io.String.Output(display_name="video_path"),
                io.String.Output(display_name="video_url"),
            ],
        )

    @classmethod
    def execute(cls, model, prompt, duration, aspect_ratio, resolution,
                slug_override="", start_image=None, end_image=None,
                start_image_url="", end_image_url="",
                reference_images: io.Autogrow.Type = None, reference_image_type="image",
                reference_video_urls="", reference_audio_url="",
                extra_params_json="", poll_interval=6.0, max_wait_seconds=1800) -> io.NodeOutput:
        import json

        slug = (slug_override or "").strip() if model == "custom" else model
        if not slug:
            raise ValueError("MagnificMCPVideo: model=custom needs a 'slug_override'.")
        has_start = bool((start_image_url or "").strip()) or start_image is not None
        if not (prompt or "").strip() and not has_start:
            raise ValueError("MagnificMCPVideo: provide a 'prompt' and/or a start image "
                             "(connect 'start_image' or set 'start_image_url').")

        clip: dict = {
            "slug": slug,
            "duration": duration,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
        }
        if (prompt or "").strip():
            clip["prompt"] = prompt

        if (extra_params_json or "").strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificMCPVideo: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificMCPVideo: extra_params_json must be a JSON object.")
            clip.update(extra)

        # Keyframes: a URL wins over the connected IMAGE for that slot.
        start_bytes = (_png_bytes(start_image)
                       if (start_image is not None and not (start_image_url or "").strip()) else None)
        end_bytes = (_png_bytes(end_image)
                     if (end_image is not None and not (end_image_url or "").strip()) else None)

        # References: autogrow images (uploaded) + video/audio URLs.
        references: list[dict] = []
        ag = reference_images or {}
        # sort by trailing slot index so refs keep a stable order
        for name in sorted(ag, key=lambda n: int(n.rsplit("_", 1)[-1]) if n.rsplit("_", 1)[-1].isdigit() else 0):
            imgs = ag[name]
            if imgs is None:
                continue
            # An IMAGE input may be a batch; take each frame as a separate reference.
            for i in range(imgs.shape[0]):
                references.append({"type": reference_image_type, "bytes": _png_bytes(imgs[i:i + 1])})
        for line in (reference_video_urls or "").splitlines():
            u = line.strip()
            if u:
                references.append({"type": "video", "url": u})
        if (reference_audio_url or "").strip():
            references.append({"type": "audio", "url": reference_audio_url.strip()})

        def _status(msg):
            print(f"[ComfyUI-Magnific] MCP/{slug}: {msg}")

        urls = mcp_client.generate_video(
            slug, clip,
            start_url=start_image_url or "", end_url=end_image_url or "",
            start_bytes=start_bytes, end_bytes=end_bytes,
            references=references or None,
            poll_interval=poll_interval, max_wait=max_wait_seconds, status_cb=_status,
        )
        video_path = mcp_client.download_to_output(urls[0], prefix=f"magnific_mcp_{slug}", ext_hint=".mp4")
        # Inline preview so the generated video shows in the node (not just a wire).
        try:
            import folder_paths
            out_dir = folder_paths.get_output_directory()
            rel = os.path.relpath(os.path.dirname(video_path), out_dir)
            subfolder = "" if rel in (".", "") else rel.replace("\\", "/")
        except Exception:  # noqa: BLE001
            subfolder = ""
        preview = ui.PreviewVideo([ui.SavedResult(os.path.basename(video_path), subfolder,
                                                  io.FolderType.output)])
        return io.NodeOutput(InputImpl.VideoFromFile(video_path), video_path, "\n".join(urls),
                             ui=preview)


NODE_CLASS_MAPPINGS = {"MagnificMCPVideo": MagnificMCPVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificMCPVideo": "Magnific MCP Video (Seedance 2.0 / Sora 2 / Kling 3)"}
