"""Shared REST client for the Magnific / Freepik AI API.

Magnific (formerly Freepik) exposes every generative endpoint behind the *same*
asynchronous task contract:

    POST /v1/ai/<endpoint>            -> { "data": { "task_id", "status", "generated": [] } }
    GET  /v1/ai/<endpoint>/{task_id}  -> same envelope; when status == COMPLETED the
                                         "generated" array holds the result URL(s).

``status`` moves CREATED -> IN_PROGRESS -> COMPLETED | FAILED. This module wraps
that lifecycle once (:class:`MagnificClient.run`) so every node just builds a body
and hands back a result URL list.

Two mirrored hosts serve identical paths:

    provider "magnific" -> https://api.magnific.com   header  x-magnific-api-key   (current)
    provider "freepik"  -> https://api.freepik.com    header  x-freepik-api-key    (legacy mirror)

The API key is resolved (in order) from the node widget, then the environment
(``MAGNIFIC_API_KEY`` / ``FREEPIK_API_KEY``), then a ``magnific_api_key.txt`` /
``freepik_api_key.txt`` file next to this pack — mirroring the ComfyUI-ClarityAI
convention so users can keep the key out of the workflow JSON.

Only ``requests`` is an external dependency; ``torch`` / ``numpy`` / ``PIL`` ship
with ComfyUI. ``folder_paths`` and ``comfy`` are imported lazily so this file can
be unit-tested outside a ComfyUI runtime.
"""
from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import requests

# ── provider table ────────────────────────────────────────────────────────────
# provider -> (base_url, auth_header, ordered env-var candidates, key-file name)
PROVIDERS: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "magnific": (
        "https://api.magnific.com",
        "x-magnific-api-key",
        ("MAGNIFIC_API_KEY", "FREEPIK_API_KEY"),
        "magnific_api_key.txt",
    ),
    "freepik": (
        "https://api.freepik.com",
        "x-freepik-api-key",
        ("FREEPIK_API_KEY", "MAGNIFIC_API_KEY"),
        "freepik_api_key.txt",
    ),
}

# Terminal task states (compared upper-cased).
_DONE = {"COMPLETED", "DONE", "SUCCESS", "SUCCEEDED", "FINISHED", "READY"}
_FAIL = {"FAILED", "ERROR", "ERRORED", "CANCELLED", "CANCELED", "REJECTED"}

_PACK_DIR = Path(__file__).resolve().parent


# ── exceptions (surfaced as ComfyUI node errors, never swallowed) ──────────────
class MagnificAPIError(RuntimeError):
    """Base error for anything that goes wrong talking to the API."""


class MagnificAuthError(MagnificAPIError):
    """401/403 — missing, invalid, or unauthorized API key."""


class MagnificPaymentError(MagnificAPIError):
    """402 — out of credits / plan does not cover this endpoint."""


class MagnificRateLimitError(MagnificAPIError):
    """429 — too many requests; retried with backoff before this is raised."""


class MagnificRequestError(MagnificAPIError):
    """400/422 — malformed request (bad params); carries the server detail."""


class MagnificTaskFailed(MagnificAPIError):
    """The task reached a FAILED/terminal-error state on the server."""


class MagnificTimeout(MagnificAPIError):
    """The task did not complete within ``max_wait`` seconds."""


# ── key resolution ─────────────────────────────────────────────────────────────
def resolve_api_key(provider: str, override: str = "") -> str:
    """Return the API key, or raise :class:`MagnificAuthError` with setup help.

    Order: explicit node widget ``override`` -> env vars for the provider ->
    ``<provider>_api_key.txt`` next to this pack.
    """
    override = (override or "").strip()
    if override:
        return override

    _base, _hdr, env_vars, key_file = PROVIDERS[provider]
    for var in env_vars:
        val = (os.environ.get(var) or "").strip()
        if val:
            return val

    fpath = _PACK_DIR / key_file
    if fpath.is_file():
        val = fpath.read_text(encoding="utf-8").strip()
        if val:
            return val

    raise MagnificAuthError(
        "No API key found. Provide it in the node's 'api_key' field, set the "
        f"{env_vars[0]} (or {env_vars[1]}) environment variable, or create "
        f"'{key_file}' next to the ComfyUI-Magnific pack. Get a key at "
        "https://www.magnific.com (API) / https://www.freepik.com/api."
    )


def make_client(provider: str, api_key_override: str = "", **kw) -> "MagnificClient":
    provider = (provider or "magnific").lower()
    if provider not in PROVIDERS:
        raise MagnificRequestError(
            f"Unknown provider '{provider}'. Use one of: {', '.join(PROVIDERS)}."
        )
    key = resolve_api_key(provider, api_key_override)
    return MagnificClient(provider=provider, api_key=key, **kw)


# ── client ─────────────────────────────────────────────────────────────────────
class MagnificClient:
    """Thin, synchronous client that owns the submit -> poll -> result lifecycle."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        request_timeout: int = 60,
        poll_interval: float = 5.0,
        max_wait: float = 900.0,
        max_retries: int = 4,
    ) -> None:
        base_url, header, _env, _kf = PROVIDERS[provider]
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.header = header
        self.api_key = api_key
        self.request_timeout = request_timeout
        self.poll_interval = max(1.0, float(poll_interval))
        self.max_wait = float(max_wait)
        self.max_retries = int(max_retries)
        self._session = requests.Session()

    # -- low level -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            self.header: self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _raise_for_status(self, resp: requests.Response, context: str) -> None:
        if resp.status_code < 400:
            return
        detail = self._error_detail(resp)
        code = resp.status_code
        msg = f"{context} failed (HTTP {code}): {detail}"
        if code in (401, 403):
            raise MagnificAuthError(msg)
        if code == 402:
            raise MagnificPaymentError(msg)
        if code == 429:
            raise MagnificRateLimitError(msg)
        if code in (400, 404, 422):
            raise MagnificRequestError(msg)
        raise MagnificAPIError(msg)

    @staticmethod
    def _error_detail(resp: requests.Response) -> str:
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001 — non-JSON error body
            return (resp.text or "").strip()[:500] or "<empty response>"
        for key in ("message", "detail", "error", "title"):
            if isinstance(data, dict) and data.get(key):
                v = data[key]
                return v if isinstance(v, str) else str(v)
        # Freepik surfaces validation issues under "invalid_params"
        if isinstance(data, dict) and data.get("invalid_params"):
            return f"invalid params: {data['invalid_params']}"
        return str(data)[:500]

    def _request(self, method: str, path: str, *, json_body=None) -> dict:
        """One HTTP call with 429/5xx backoff; returns the parsed JSON dict."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self._session.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    json=json_body,
                    timeout=self.request_timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt, 10))
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                # Honour Retry-After when present, else exponential backoff.
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after or "").isdigit() else min(2 ** attempt, 15)
                last_exc = MagnificRateLimitError(
                    f"{method} {path}: transient HTTP {resp.status_code}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
                    continue

            self._raise_for_status(resp, f"{method} {path}")
            try:
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                raise MagnificAPIError(
                    f"{method} {path}: response was not JSON: {(resp.text or '')[:300]}"
                ) from exc

        raise MagnificAPIError(
            f"{method} {path}: giving up after {self.max_retries} attempts "
            f"({last_exc})"
        )

    # -- task lifecycle --------------------------------------------------------
    @staticmethod
    def _data(envelope: dict) -> dict:
        """Return the ``data`` block (Freepik wraps everything in ``data``)."""
        if isinstance(envelope, dict):
            d = envelope.get("data")
            if isinstance(d, dict):
                return d
            if isinstance(d, list) and d and isinstance(d[0], dict):
                return d[0]
            return envelope
        return {}

    @staticmethod
    def _status(data: dict) -> str:
        # Endpoints are inconsistent: most use "status", style-transfer uses
        # "task_status"; accept either (plus "state") so polling never stalls.
        return str(data.get("status") or data.get("state")
                   or data.get("task_status") or "").upper()

    def submit(self, path: str, body: dict) -> dict:
        """POST the task; return the ``data`` block (has ``task_id`` + ``status``)."""
        env = self._request("POST", path, json_body=body)
        return self._data(env)

    def get_task(self, path: str, task_id: str) -> dict:
        env = self._request("GET", f"{path.rstrip('/')}/{task_id}")
        return self._data(env)

    def run(
        self,
        path: str,
        body: dict,
        *,
        on_status: Optional[Callable[[str, float], None]] = None,
        check_interrupt: Optional[Callable[[], None]] = None,
    ) -> list[str]:
        """Submit *body* to *path*, poll to completion, return the result URL(s).

        ``on_status(status, elapsed)`` is called after submit and each poll so a
        node can log progress. ``check_interrupt()`` (if given) is called each
        poll and may raise to abort a long generation from the ComfyUI UI.
        """
        started = time.time()
        data = self.submit(path, body)
        task_id = data.get("task_id") or data.get("id") or data.get("taskId")
        status = self._status(data)
        if on_status:
            on_status(status or "CREATED", 0.0)

        # Some endpoints may already return the finished URLs on submit.
        if status in _DONE:
            urls = self.extract_urls(data)
            if urls:
                return urls
        if status in _FAIL:
            raise MagnificTaskFailed(f"{path}: task {task_id} returned status {status}")
        if not task_id:
            raise MagnificAPIError(
                f"{path}: submit returned no task_id (body: {str(data)[:300]})"
            )

        while True:
            if check_interrupt:
                check_interrupt()
            if time.time() - started > self.max_wait:
                raise MagnificTimeout(
                    f"{path}: task {task_id} not finished after {self.max_wait:.0f}s "
                    f"(last status {status})."
                )
            time.sleep(self.poll_interval)
            data = self.get_task(path, task_id)
            status = self._status(data)
            if on_status:
                on_status(status or "IN_PROGRESS", time.time() - started)
            if status in _FAIL:
                reason = data.get("error") or data.get("message") or ""
                raise MagnificTaskFailed(
                    f"{path}: task {task_id} FAILED. {reason}".strip()
                )
            if status in _DONE:
                urls = self.extract_urls(data)
                if not urls:
                    raise MagnificAPIError(
                        f"{path}: task {task_id} COMPLETED but returned no asset URL "
                        f"(body: {str(data)[:300]})"
                    )
                return urls

    @staticmethod
    def extract_urls(data: dict) -> list[str]:
        """Pull result URLs out of a completed task's ``data`` block.

        ``generated`` is normally a list of URL strings, but the API has also
        been seen returning a list of objects ({"url": ...}) — handle both, and
        fall back to other common asset keys.
        """
        out: list[str] = []

        def _add(v: Any) -> None:
            if isinstance(v, str) and v.startswith("http"):
                out.append(v)
            elif isinstance(v, dict):
                for k in ("high_resolution", "url", "image_url", "video_url",
                          "audio_url", "download_url"):
                    if isinstance(v.get(k), str) and v[k].startswith("http"):
                        out.append(v[k])
                        break

        gen = data.get("generated")
        if isinstance(gen, list):
            for item in gen:
                _add(item)
        elif gen is not None:
            _add(gen)

        if not out:
            for key in ("high_resolution", "result", "output", "url", "audio", "video"):
                _add(data.get(key))

        # De-dup, keep order.
        seen: set[str] = set()
        return [u for u in out if not (u in seen or seen.add(u))]

    def post_form_sync(self, path: str, data: dict) -> list[str]:
        """POST a form-encoded, *synchronous* endpoint and return result URL(s).

        A few endpoints (e.g. beta/remove-background) don't use the async task
        contract: they take ``application/x-www-form-urlencoded`` and return the
        finished asset URL(s) directly. Shares the 429/5xx backoff of ``_request``.
        """
        headers = {self.header: self.api_key, "Accept": "application/json"}
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self._session.post(
                    self._url(path), headers=headers, data=data,
                    timeout=max(self.request_timeout, 120),
                )
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(min(2 ** attempt, 10))
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < self.max_retries - 1:
                time.sleep(min(2 ** attempt, 15))
                continue
            self._raise_for_status(resp, f"POST {path}")
            try:
                body = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise MagnificAPIError(
                    f"POST {path}: response was not JSON: {(resp.text or '')[:300]}"
                ) from exc
            urls = self.extract_urls(self._data(body))
            if not urls:
                raise MagnificAPIError(
                    f"POST {path}: no result URL in response: {str(body)[:300]}"
                )
            return urls
        raise MagnificAPIError(
            f"POST {path}: giving up after {self.max_retries} attempts ({last_exc})"
        )

    # -- downloads -------------------------------------------------------------
    def download_bytes(self, url: str) -> bytes:
        resp = self._session.get(url, timeout=max(self.request_timeout, 120))
        resp.raise_for_status()
        return resp.content


# ── image / file helpers (torch + PIL, provided by ComfyUI) ────────────────────
def _lazy_imports():
    import numpy as np  # noqa: WPS433
    import torch  # noqa: WPS433
    from PIL import Image  # noqa: WPS433

    return np, torch, Image


def tensor_to_base64_png(image, index: int = 0) -> str:
    """Encode one frame of a ComfyUI IMAGE tensor ([B,H,W,C], 0..1) as base64 PNG.

    Returns a raw base64 string (no ``data:`` prefix) — the format the Magnific
    endpoints accept for reference/source images.
    """
    np, _torch, Image = _lazy_imports()
    arr = image[index] if image.ndim == 4 else image
    arr = (arr.detach().cpu().numpy() * 255.0).clip(0, 255).astype("uint8")
    if arr.ndim == 2:  # grayscale
        img = Image.fromarray(arr, mode="L").convert("RGB")
    else:
        img = Image.fromarray(arr[:, :, :3], mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def bytes_to_image_tensor(data: bytes):
    """Decode image bytes into a ComfyUI IMAGE tensor [1,H,W,3] float32 0..1."""
    np, torch, Image = _lazy_imports()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(img).astype("float32") / 255.0
    return torch.from_numpy(arr)[None, ]


def urls_to_image_batch(client: MagnificClient, urls: Iterable[str]):
    """Download image URLs into a single batched IMAGE tensor.

    Frames of identical size are stacked into one [N,H,W,3] batch; if sizes
    differ, each is returned as its own batch item is impossible, so we keep the
    first and warn (ComfyUI batches require matching dims).
    """
    np, torch, _Image = _lazy_imports()
    tensors = [bytes_to_image_tensor(client.download_bytes(u)) for u in urls]
    if not tensors:
        raise MagnificAPIError("No images were returned to download.")
    shapes = {t.shape for t in tensors}
    if len(shapes) == 1:
        return torch.cat(tensors, dim=0)
    print(
        "[ComfyUI-Magnific] Returned images have differing dimensions "
        f"{[tuple(t.shape[1:]) for t in tensors]}; returning the first only. "
        "Run separate generations if you need all sizes."
    )
    return tensors[0]


def save_url_to_output(client: MagnificClient, url: str, prefix: str, ext_hint: str = "") -> str:
    """Download *url* into ComfyUI's output dir; return the absolute file path.

    Used for video/audio results, which ComfyUI has no single native tensor for —
    a file path is the most portable thing to hand downstream nodes.
    """
    try:
        import folder_paths  # type: ignore

        out_dir = Path(folder_paths.get_output_directory())
    except Exception:  # noqa: BLE001 — outside ComfyUI (tests)
        out_dir = _PACK_DIR / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Derive extension from the URL path, else the hint, else .bin.
    url_path = url.split("?", 1)[0]
    ext = os.path.splitext(url_path)[1].lower()
    if not ext:
        ext = ext_hint if ext_hint.startswith(".") else (f".{ext_hint}" if ext_hint else ".bin")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    idx = 0
    while True:
        name = f"{prefix}_{stamp}{'' if idx == 0 else f'_{idx}'}{ext}"
        dest = out_dir / name
        if not dest.exists():
            break
        idx += 1

    dest.write_bytes(client.download_bytes(url))
    print(f"[ComfyUI-Magnific] Saved result -> {dest}")
    return str(dest)


def output_media_preview(path: str, key: str = "images") -> dict:
    """Build the ComfyUI UI payload that previews a saved file inline.

    Mirrors ``comfy_api.latest.ui.PreviewVideo`` — ``{key: [{filename, subfolder,
    type}], "animated": (True,)}`` — so an OUTPUT_NODE shows the generated video (or
    audio) in the node itself, not just a wire. *path* must live under ComfyUI's
    output directory (where ``save_url_to_output`` writes it).
    """
    try:
        import folder_paths  # type: ignore

        out_dir = folder_paths.get_output_directory()
    except Exception:  # noqa: BLE001 — outside ComfyUI (tests)
        out_dir = str(_PACK_DIR / "output")
    filename = os.path.basename(path)
    try:
        rel = os.path.relpath(os.path.dirname(path), out_dir)
        subfolder = "" if rel in (".", "") else rel.replace("\\", "/")
    except Exception:  # noqa: BLE001
        subfolder = ""
    return {key: [{"filename": filename, "subfolder": subfolder, "type": "output"}],
            "animated": (True,)}


def comfy_interrupt_checker() -> Callable[[], None]:
    """Return a callable that raises if the user pressed Cancel in ComfyUI.

    No-op outside a ComfyUI runtime so the client stays testable.
    """
    try:
        import comfy.model_management as mm  # type: ignore

        return mm.throw_exception_if_processing_interrupted
    except Exception:  # noqa: BLE001
        return lambda: None
