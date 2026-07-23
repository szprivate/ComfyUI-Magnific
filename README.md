# ComfyUI-Magnific

ComfyUI custom nodes that wrap the **Magnific / Freepik** AI REST API — image
generation, creative & precise upscaling, video, references and text-to-speech —
mirroring the Magnific MCP tool set as native ComfyUI nodes.

> Magnific and Freepik are the same platform on two mirrored API hosts. These
> nodes support both and default to Magnific (the current surface). You do **not**
> need to know which host your key belongs to — pick the matching `provider`.

## Nodes (category **Magnific**)

| Node | Endpoint | Output |
|------|----------|--------|
| **Magnific Image Generate (Mystic)** | `POST /v1/ai/mystic` | `IMAGE`, `image_urls` |
| **Magnific Upscale** | `POST /v1/ai/image-upscaler` (creative) / `…/image-upscaler-precision` (precise) | `IMAGE`, `image_url` |
| **Magnific Video Generate** | `POST /v1/ai/{image,text}-to-video/<model>` | `video_path`, `video_url` |
| **Magnific Reference Create (Soul)** | *(local — packages a reference image)* | `MAGNIFIC_REFERENCE` |
| **Magnific Text-to-Speech** | `POST /v1/ai/voiceover` | `audio_path`, `audio_url` |

Every generation endpoint is **asynchronous**: the node submits a task, polls
`GET /v1/ai/<endpoint>/{task_id}` until the status is `COMPLETED` (or `FAILED`),
then downloads the result. Images come back as ComfyUI `IMAGE` tensors; video and
audio are saved into your ComfyUI `output/` folder and the file path is returned.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/szprivate/ComfyUI-Magnific
pip install -r ComfyUI-Magnific/requirements.txt   # or use ComfyUI's embedded python
```

Then restart ComfyUI. (`requests` is the only extra dependency; `torch`, `numpy`
and `Pillow` already ship with ComfyUI.)

## API key setup

Get a key from the [Magnific API](https://www.magnific.com) or
[Freepik API](https://www.freepik.com/api) dashboard. The nodes resolve the key
in this order:

1. The node's **`api_key`** widget (masked). Convenient, but it is saved into the
   workflow JSON — prefer options 2/3 if you share workflows.
2. Environment variable **`MAGNIFIC_API_KEY`** (or **`FREEPIK_API_KEY`**).
3. A **`magnific_api_key.txt`** (or `freepik_api_key.txt`) file placed next to this
   pack, containing just the key.

Set `provider` on each node to `magnific` (→ `api.magnific.com`, header
`x-magnific-api-key`) or `freepik` (→ `api.freepik.com`, header
`x-freepik-api-key`). Both env vars work for either provider.

## Example workflow

`example_workflows/mystic_txt2img.json` — a minimal **Mystic → Preview Image**
graph. Drag it onto the ComfyUI canvas, set your API key on the node, edit the
prompt and press **Queue**. It doubles as a starting point: feed the `images`
output into **Magnific Upscale**, or wire a **Magnific Reference Create** node into
the `reference` input.

## Notes & conventions

- **Reference / source images** accept either a connected ComfyUI `IMAGE` (encoded
  to base64 PNG) or a public `*_url` string (used as-is, max quality, no upload).
- **`Magnific Reference Create`** packages an image + role (`style` / `structure` /
  `character`) + strength into a `MAGNIFIC_REFERENCE` you feed into the Mystic
  node's `reference` input. The public API has no standalone "register a Soul
  reference" endpoint — references are supplied inline at generation time — so this
  node prepares that payload. If Magnific ships a dedicated endpoint later, it slots
  into `nodes/reference.py`.
- **Video models.** Each model is its own endpoint (`VIDEO_MODELS` in
  `nodes/video_generate.py`) and they do **not** share one request schema, so the
  body is built per model *family* and filtered to that family's fields:
  - **Kling** (`kling-*`) — confirmed: sends `cfg_scale`, `generate_audio`,
    `negative_prompt`.
  - **Seedance** (`seedance-pro-1080p`) — confirmed: sends `camera_fixed`,
    `frames_per_second`, `seed` (Kling-only fields are **not** sent).
  - **MiniMax/Hailuo, PixVerse, Wan, Runway, LTX** — best-effort: only the common
    fields (`prompt`, `duration`, `aspect_ratio`, `image`) are sent; supply any
    model-specific parameters via `extra_params_json`.

  If Magnific renames a slug, update `VIDEO_MODELS` or paste the exact path into the
  node's `endpoint_override` widget — no code change needed.
- **`extra_params_json`** on each generating node lets you pass any additional
  documented API parameter (e.g. Mystic's `styling` object) as a JSON object that
  is merged into the request body.
- **Errors are surfaced, never silent.** `401/403` (bad key), `402` (out of
  credits), `429` (rate limit — retried with backoff first), `400/422` (bad params
  with the server's detail) and task `FAILED`/timeout all raise a node error you
  see in the ComfyUI UI. Long generations can be cancelled from the UI mid-poll.

## Disclaimer

Not affiliated with Magnific or Freepik. Endpoint paths and parameters follow the
public docs at <https://docs.magnific.com> / <https://docs.freepik.com>; some
optional parameter enums may evolve — use `extra_params_json` / `endpoint_override`
to stay ahead of doc drift.
