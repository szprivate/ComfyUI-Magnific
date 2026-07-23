"""Shared building blocks for the Magnific nodes.

Keeps the auth/connection widgets, client construction, progress logging and
image-input coercion in one place so the five node modules stay focused on their
endpoint's parameters.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow ``from freepik_api import ...`` whether the pack is imported as a package
# (ComfyUI) or the module is run directly (tests).
_PACK_DIR = Path(__file__).resolve().parent.parent
if str(_PACK_DIR) not in sys.path:
    sys.path.insert(0, str(_PACK_DIR))

from freepik_api import (  # noqa: E402
    MagnificClient,
    comfy_interrupt_checker,
    make_client,
    tensor_to_base64_png,
)

CATEGORY = "Magnific"
PROVIDER_CHOICES = ["magnific", "freepik"]


def connection_inputs() -> dict[str, Any]:
    """The auth/connection widgets shared by every generating node.

    Returned as the ``required``-style dict fragment; nodes splice it into their
    own ``INPUT_TYPES``. ``api_key`` is a password-masked widget (ComfyUI hides
    inputs flagged ``password: True``).
    """
    return {
        "provider": (PROVIDER_CHOICES, {"default": "magnific"}),
        "api_key": ("STRING", {
            "default": "",
            "multiline": False,
            "password": True,
            "tooltip": "Leave blank to use the MAGNIFIC_API_KEY / FREEPIK_API_KEY "
                       "env var or a *_api_key.txt file next to the pack.",
        }),
    }


def polling_inputs() -> dict[str, Any]:
    """Optional widgets controlling the async poll loop (sane defaults)."""
    return {
        "poll_interval": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 60.0, "step": 0.5}),
        "max_wait_seconds": ("INT", {"default": 900, "min": 30, "max": 3600, "step": 30}),
    }


def build_client(provider: str, api_key: str, poll_interval: float = 5.0,
                 max_wait_seconds: int = 900) -> MagnificClient:
    return make_client(
        provider,
        api_key_override=api_key,
        poll_interval=poll_interval,
        max_wait=max_wait_seconds,
    )


def make_logger(tag: str):
    """A status callback that prints '<tag>: STATUS (Ns)' to the ComfyUI console."""
    def _log(status: str, elapsed: float) -> None:
        print(f"[ComfyUI-Magnific] {tag}: {status} ({elapsed:.0f}s)")
    return _log


def image_to_payload(image=None, image_url: str = "") -> str:
    """Resolve a reference/source image input into the string the API expects.

    Prefers an explicit ``image_url`` (public URL, max quality, no upload); else
    encodes a ComfyUI IMAGE tensor as base64 PNG. Returns "" if neither is set.
    """
    url = (image_url or "").strip()
    if url:
        return url
    if image is not None:
        return tensor_to_base64_png(image)
    return ""


__all__ = [
    "CATEGORY",
    "PROVIDER_CHOICES",
    "connection_inputs",
    "polling_inputs",
    "build_client",
    "make_logger",
    "image_to_payload",
    "comfy_interrupt_checker",
]
