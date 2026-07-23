"""MagnificReferenceCreate — build a Soul-style character/style reference.

The public Magnific/Freepik API has no standalone "register a Soul reference"
endpoint; references are supplied inline to generation as base64 images (Mystic's
``style_reference`` / ``structure_reference`` fields and the ``styling.characters``
list). This node packages one input image into a reusable MAGNIFIC_REFERENCE
object — encoding it once, tagging its role and strength — which
``MagnificImageGenerate`` then drops into the matching slot. If Magnific later
ships a dedicated reference-registration endpoint, this node is where to wire it.
"""
from __future__ import annotations

from ._common import CATEGORY, image_to_payload

ROLES = ["style", "structure", "character"]


class MagnificReferenceCreate:
    """Package an image as a reusable style/structure/character reference."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "role": (ROLES, {"default": "style"}),
                "strength": ("INT", {"default": 100, "min": 0, "max": 100}),
            },
            "optional": {
                "image_url": ("STRING", {"default": ""}),
                "name": ("STRING", {"default": "reference"}),
            },
        }

    RETURN_TYPES = ("MAGNIFIC_REFERENCE",)
    RETURN_NAMES = ("reference",)
    FUNCTION = "create"
    CATEGORY = CATEGORY

    def create(self, image, role, strength, image_url="", name="reference"):
        payload = image_to_payload(image, image_url)
        if not payload:
            raise ValueError("MagnificReferenceCreate: an 'image' (or 'image_url') is required.")
        reference = {
            "role": role,
            "strength": strength,
            "name": name or "reference",
            # b64 holds either the base64 PNG or the passthrough URL — both are
            # accepted wherever Mystic takes a *_reference value.
            "b64": payload,
        }
        return (reference,)


NODE_CLASS_MAPPINGS = {"MagnificReferenceCreate": MagnificReferenceCreate}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificReferenceCreate": "Magnific Reference Create (Soul)"}
