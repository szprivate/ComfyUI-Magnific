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
| **Magnific Text-to-Image** | `POST /v1/ai/text-to-image/<model>` (Flux, Seedream, Z-Image, Hyperflux, Runway) | `IMAGE`, `image_urls` |
| **Magnific Image Edit** | style transfer, Kontext edit, relight, remove bg, expand, reimagine | `IMAGE`, `image_urls` |
| **Magnific Upscale** | `POST /v1/ai/image-upscaler` (creative) / `…/image-upscaler-precision` (precise) | `IMAGE`, `image_url` |
| **Magnific Video Generate** | `POST /v1/ai/{image,text}-to-video/<model>` (Kling 2.x, Seedance, Hailuo, Wan, PixVerse, Runway, LTX) | `video_path`, `video_url` |
| **Magnific Video Advanced** | `POST /v1/ai/video/<model>` — Kling 3, Kling 3 Omni, OmniHuman 1.5, Act-Two, VFX | `video_path`, `video_url` |
| **Magnific Reference Create (Soul)** | *(local — packages a reference image)* | `MAGNIFIC_REFERENCE` |
| **Magnific Text-to-Speech** | `POST /v1/ai/voiceover` | `audio_path`, `audio_url` |
| **Magnific Audio Generate** | `POST /v1/ai/music-generation` / `…/sound-effects` | `audio_path`, `audio_url` |
| **Magnific Audio Isolation** | `POST /v1/ai/audio-isolation` | `audio_path`, `audio_url` |
| **Magnific MCP Video** | Magnific **MCP** `video_generate` (OAuth) — Seedance 2.0, Sora 2, Kling 3, Veo 3.1 | `video_path`, `video_url` |

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

## Model coverage & verification status

Paths below were verified against real curl examples / the API reference.
**Path** = the endpoint is confirmed; **Params** = the request body fields the node
sends are confirmed. Where params are *best-effort*, the path is right and the common
fields are sent — pass anything model-specific via `extra_params_json`.

| Category | Models | Path | Params |
|----------|--------|------|--------|
| Image (Mystic) | `mystic` | ✅ | ✅ |
| Image (text-to-image) | `flux-dev`, `flux-pro-v1-1`, `flux-2-pro/turbo/klein`, `hyperflux`, `seedream`, `seedream-4`, `seedream-v4-5`, `z-image-turbo`, `runway`, `classic` | ✅ | ⚠️ prompt/aspect_ratio/seed sent; rest via `extra_params_json` |
| Image edit | `style-transfer`, `flux-kontext-pro`, `remove-background` | ✅ | ✅ |
| Image edit | `relight`, `reimagine-flux`, `seedream-v4-5-edit`, `image-expand` | ✅ | ⚠️ best-effort |
| Upscale | `image-upscaler` (creative), `image-upscaler-precision` | ✅ | ✅ |
| Video i2v | `kling-v2-6-pro` | ✅ | ✅ |
| Video i2v | `seedance-pro-1080p` | ✅ | ✅ |
| Video i2v | `kling-v2-5/2-1-pro`, `kling-o1-pro`, `kling-motion`, `minimax-hailuo-2-3/02`, `minimax-video-01-live`, `pixverse`, `wan-2-5-i2v`, `wan-v2-6`, `runway-gen4-turbo` | ✅ | ⚠️ common fields; rest via `extra_params_json` |
| Video t2v | `wan-2-5-t2v-1080p`, `ltx-2-pro` | ✅ | ⚠️ common fields |
| Video (v3 group) | `kling-v3-pro`, `omni-human-1-5` | ✅ | ✅ |
| Video (v3 group) | `kling-v3-omni-pro`, `kling-v3-omni-std`, `runway-act-two`, `vfx` | ✅ | ⚠️ best-effort |
| Audio | `voiceover` (TTS), `music-generation`, `audio-isolation` | ✅ | ✅ |
| Audio | `sound-effects` | ✅ | ⚠️ best-effort |

**Newer models:**
- **Kling 3.0 / Kling 3 Omni** — available via `MagnificVideoAdvanced` (`kling-v3-pro`,
  `kling-v3-omni-pro`, `kling-v3-omni-std`). They use a different schema from Kling 2.x
  (URL-based `start_image_url`/`end_image_url`, `16:9`-style aspect ratio, 3–15s), which
  is why they live in a separate node.
- **Seedance 2.0** — available in the Magnific **MCP** but **not on the REST API** this
  pack wraps (only an older `seedance-pro-1080p` endpoint exists). Not wired; see
  [REST API vs the Magnific MCP](#rest-api-vs-the-magnific-mcp) below.

**Notable per-endpoint quirks the nodes already handle:**
- `flux-kontext-pro` and `remove-background` accept an image **URL only** (not base64) —
  set `image_url`; the node errors clearly if you pass only a tensor.
- `remove-background` is **synchronous** and form-encoded (no task polling) — handled
  via a dedicated sync path.
- `style-transfer` reports progress under `task_status` (not `status`) — the poller
  reads both, so it won't stall.

All catalogued generative endpoints are now wired. The remaining API surface is
non-generative (stock content search, team/usage analytics) and out of scope for a
generation node pack.

## REST API vs the Magnific MCP

This pack wraps the **REST API** (`api.freepik.com` / `api.magnific.com`, `x-*-api-key`).
Magnific also ships a separate **MCP server** (`mcp.magnific.com`, OAuth) used by AI
assistants — and the two are **not the same catalog**. They don't even share a shape: the
REST API exposes each model as its own endpoint (`/v1/ai/…/<model>`), while the MCP has a
single generic `video_generate` whose model is a **`slug`** chosen from a much larger,
more up-to-date catalog (~49 video models vs the REST subset).

So some models you can use in a Magnific/Freepik AI *assistant* have **no REST endpoint
yet** and therefore cannot be wired here. Most relevant:

| Model | Magnific MCP slug | REST endpoint (this pack) |
|-------|-------------------|---------------------------|
| **Seedance 2.0 / Fast / Mini** | `bytedance-seedance-pro-2.0`, `…-fast-2.0`, `…-mini-2.0` | ❌ none |
| Seedance 1.5 Pro | `bytedance-seedance-pro-1.5` | ❌ none |
| Seedance (older Pro) | — | ✅ `seedance-pro-1080p` |
| Kling 3.0 / Omni / Turbo | `kling-30`, `kling-omni3`, `kling-30-turbo` | ✅ `kling-v3-pro` (+ partial) |
| OpenAI Sora 2 / Pro | `openai-sora2-standard`, `openai-sora2-pro` | ❌ none |
| Google Veo 3.1 | `google-veo3_1` | ❌ none |

Note the REST `seedance-pro-1080p` is an **older** Seedance (the MCP lists 1.5 and 2.0 as
distinct slugs) — not the same model as MCP "Seedance 2.0".

**To use these REST-missing models, the `Magnific MCP Video` node bridges to the MCP**
(see setup below). New models also reach the REST API eventually; when a REST slug
appears it drops straight into `VIDEO_MODELS` (`nodes/video_generate.py`) or `ADV_MODELS`
(`nodes/video_advanced.py`).

### `Magnific MCP Video` node — setup

This one node talks to the Magnific **MCP** (OAuth) instead of the REST API, so it can
reach the full video catalog by `slug`. It is self-contained — its own OAuth
registration and token store, no dependency on any other app.

1. **Install `mcp`** into the same Python that runs ComfyUI: `pip install mcp`.
   (The REST nodes don't need it; if it's missing, only this node is skipped.)
2. **Authorize once** — from the pack folder, with ComfyUI's Python:
   ```bash
   python authorize_magnific.py
   ```
   A browser opens to sign in to Magnific; tokens are saved to `.mcp_tokens/`
   (gitignored) and refreshed silently afterwards. Re-run if the node reports it needs
   re-authorization.
3. **Use the node** — pick a `model` slug (`bytedance-seedance-pro-2.0`, `kling-30`,
   `openai-sora2-standard`, …, or `custom` + `slug_override`), set `prompt` / `duration` /
   `aspect_ratio` / `resolution`. For image-to-video, connect a ComfyUI **IMAGE** to
   `start_image` (and/or `end_image`) — it's uploaded to the MCP automatically
   (`request_upload → PUT → finalize`) — or give a public `start_image_url` (a URL wins
   over the tensor for that slot).

> Auth note: this node uses **OAuth**, unrelated to the `MAGNIFIC_API_KEY` / `FREEPIK_API_KEY`
> used by the REST nodes. Allowed `duration` / `aspect_ratio` / `resolution` vary per model
> — the MCP surfaces an error if a combo is invalid; pass extras via `extra_params_json`.

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
