"""Self-contained OAuth client for the Magnific MCP server (mcp.magnific.com).

The REST API this pack mostly wraps only exposes a curated subset of models. The
Magnific **MCP** offers a much larger, more current catalog (Seedance 2.0, Sora 2,
Veo 3.1, ...) via a generic ``video_generate`` tool whose model is a ``slug``. This
module lets the MagnificMCPVideo node reach those models.

Auth is OAuth 2.0 (no API key). It is a one-time interactive step — run
``authorize_magnific.py`` once to sign in via the browser; tokens are stored in
``<pack>/.mcp_tokens/`` (gitignored) and refreshed silently thereafter. This is the
pack's **own** OAuth registration — it does not read any other app's tokens.

``mcp`` is imported lazily inside functions so the rest of the pack (the REST
nodes) loads fine even when ``mcp`` isn't installed; the MCP node then raises a
clear "pip install mcp" error only if actually used.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional

MCP_URL = "https://mcp.magnific.com"
PACK_DIR = Path(__file__).resolve().parent
TOKEN_DIR = PACK_DIR / ".mcp_tokens"
REDIRECT_PORT = 8207  # this pack's own OAuth redirect port

_DONE = {"done", "completed", "complete", "succeeded", "success", "finished", "ready", "generated"}
_FAIL = {"failed", "error", "errored", "cancelled", "canceled", "rejected"}
_VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v", ".mkv", ".gif")
_MEDIA_EXT = _VIDEO_EXT + (".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)


class MCPError(RuntimeError):
    """MCP call failed (tool error, bad response, or task failure)."""


class MCPAuthError(MCPError):
    """No usable token — run authorize_magnific.py first (or re-run to refresh)."""


class MCPNotInstalled(MCPError):
    """The `mcp` package isn't installed in this Python environment."""


class MCPTimeout(MCPError):
    """The generation didn't finish within max_wait."""


def _require_mcp():
    try:
        import mcp  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise MCPNotInstalled(
            "The 'mcp' package is required for the Magnific MCP node. Install it into "
            "ComfyUI's Python: pip install mcp"
        ) from exc


def has_tokens() -> bool:
    return (TOKEN_DIR / "magnific.token.json").exists()


# ── OAuth token storage (disk, this pack's own dir) ───────────────────────────
def _make_token_storage():
    from mcp.client.auth import TokenStorage
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

    tok_path = TOKEN_DIR / "magnific.token.json"
    cli_path = TOKEN_DIR / "magnific.client.json"

    class _DiskTokenStorage(TokenStorage):
        async def get_tokens(self):
            if not tok_path.exists():
                return None
            try:
                return OAuthToken.model_validate_json(tok_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None

        async def set_tokens(self, tokens) -> None:
            TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            tok_path.write_text(tokens.model_dump_json(), encoding="utf-8")

        async def get_client_info(self):
            if not cli_path.exists():
                return None
            try:
                return OAuthClientInformationFull.model_validate_json(cli_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None

        async def set_client_info(self, info) -> None:
            TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            cli_path.write_text(info.model_dump_json(), encoding="utf-8")

    return _DiskTokenStorage()


def _make_provider(interactive: bool, holder: Optional[dict]):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    metadata = OAuthClientMetadata(
        client_name="ComfyUI-Magnific",
        redirect_uris=[f"http://localhost:{REDIRECT_PORT}/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    async def redirect_handler(authorization_url: str) -> None:
        if not interactive:
            raise MCPAuthError(
                "Magnific MCP not authorized (or token expired). Run "
                "authorize_magnific.py once to sign in."
            )
        try:
            webbrowser.open(authorization_url)
        except Exception:  # noqa: BLE001
            pass
        print(f"\n[ComfyUI-Magnific] Authorize in your browser:\n  {authorization_url}\n")

    async def callback_handler():
        if not interactive or holder is None:
            raise MCPAuthError("interactive OAuth callback not available")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, holder["event"].wait, 300)
        code = holder.get("code")
        if not code:
            raise MCPError("OAuth callback timed out or returned no code")
        return code, holder.get("state")

    return OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=metadata,
        storage=_make_token_storage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def _start_callback_server(port: int) -> dict:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    holder: dict = {"event": threading.Event()}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            holder["code"] = (q.get("code") or [None])[0]
            holder["state"] = (q.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>ComfyUI-Magnific: Magnific authorized.</h2>"
                             b"<p>You can close this tab and return to ComfyUI.</p>")
            holder["event"].set()

        def log_message(self, *a):  # silence
            return

    srv = HTTPServer(("127.0.0.1", port), _Handler)
    holder["server"] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return holder


# ── async core ─────────────────────────────────────────────────────────────
async def _with_session(op: Callable, *, interactive=False, holder=None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    provider = _make_provider(interactive, holder)
    async with streamablehttp_client(MCP_URL, auth=provider) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await op(session)


async def _call(session, name: str, args: dict):
    """Call a tool; return (text, data, is_error).

    ``data`` is the best machine-readable view: the MCP ``structuredContent`` when
    it's a dict (the machine channel), else JSON parsed from the text blocks. The
    raw joined ``text`` is always returned too — several Magnific tools reply with
    TOON / key:value text (e.g. ``creations_search``, ``creations_get``) rather
    than JSON, and the human-facing ``<system_reminder>`` also arrives as text.
    """
    res = await session.call_tool(name, args)
    texts = []
    for block in getattr(res, "content", None) or []:
        t = getattr(block, "text", None)
        if t:
            texts.append(str(t))
    text = "\n".join(texts)
    parsed = None
    stripped = text.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except Exception:  # noqa: BLE001
            parsed = None
    structured = getattr(res, "structuredContent", None)
    data = structured if isinstance(structured, dict) else parsed
    return text, data, bool(getattr(res, "isError", False))


# ── response parsing (creations are key:value text or json) ──────────────────
def _parse_kv_text(text: str) -> Optional[dict]:
    if not text or not isinstance(text, str):
        return None
    out: dict = {}
    for line in text.splitlines():
        if not line or line[0] in (" ", "\t") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if not key or " " in key or key in out:
            continue
        out[key] = val.strip().strip('"').strip()
    return out or None


_IDENT_LINE_RE = re.compile(r'(?mi)^\s*-?\s*identifier:\s*"?([A-Za-z0-9_-]{6,})"?')


def _deep_find_identifier(node) -> Optional[str]:
    """First value of an ``identifier`` (or ``id``) key anywhere in a dict/list."""
    if isinstance(node, dict):
        for key in ("identifier", "id"):
            v = node.get(key)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v).strip()
        for v in node.values():
            r = _deep_find_identifier(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _deep_find_identifier(v)
            if r:
                return r
    return None


def _extract_identifier(js, text: str) -> Optional[str]:
    """Pull the (newest / first) creation identifier from a tool response.

    Handles: a ``creations:[{identifier}]`` envelope, any nested ``identifier``/
    ``id`` key in ``structuredContent``/JSON, and TOON/key:value text where the
    first ``identifier:`` line is the newest creation (``creations_search`` lists
    newest-first). Returns None if none present — e.g. ``video_generate`` replies
    only a ``<system_reminder>`` on no-UI clients, so the caller then recovers the
    id via ``creations_search``.
    """
    if isinstance(js, dict):
        cr = js.get("creations")
        if isinstance(cr, list) and cr and isinstance(cr[0], dict):
            ident = cr[0].get("identifier") or cr[0].get("id")
            if ident:
                return str(ident)
        d = _deep_find_identifier(js)
        if d:
            return d
    mo = _IDENT_LINE_RE.search(text or "")
    if mo:
        return mo.group(1)
    return None


async def _latest_video_identifier(session) -> Optional[str]:
    """Newest video creation's identifier via creations_search (raw TOON text)."""
    text, data, err = await _call(session, "creations_search",
                                  {"from": "history", "fileType": "video", "page": 1})
    if err:
        return None
    return _extract_identifier(data, text)


async def _await_new_video_identifier(session, previous: Optional[str],
                                      status_cb, timeout: float = 60.0) -> Optional[str]:
    """Poll creations_search until a *new* video creation (id != previous) appears.

    video_generate on a no-UI client returns no identifier in its response, so we
    detect the creation it just queued as "the newest one that wasn't there before
    we submitted" — avoiding grabbing a stale prior creation.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        cur = await _latest_video_identifier(session)
        if cur and cur != previous:
            return cur
        if status_cb:
            status_cb("queued — locating creation")
        await asyncio.sleep(3.0)
    # Last resort: whatever is newest now (may still be the just-submitted one).
    return await _latest_video_identifier(session)


def _status_of(body) -> Optional[str]:
    if isinstance(body, dict):
        cr = body.get("creations")
        if isinstance(cr, list) and cr and isinstance(cr[0], dict):
            body = cr[0]
        s = body.get("status") or body.get("state")
        return str(s).lower() if s else None
    return None


def _asset_url(body) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    node = body
    cr = body.get("creations")
    if isinstance(cr, list) and cr and isinstance(cr[0], dict):
        node = cr[0]
    for k in ("url", "assetUrl", "asset_url", "videoUrl", "video_url", "outputUrl", "downloadUrl"):
        v = node.get(k)
        if isinstance(v, str) and v.lower().startswith("http") and "/app/creation/" not in v:
            return v
    # fallback: any media URL in the serialized body, excluding the viewer page
    try:
        blob = json.dumps(body)
    except Exception:  # noqa: BLE001
        blob = str(body)
    for cand in _URL_RE.findall(blob):
        low = cand.split("?", 1)[0].lower()
        if low.endswith(_MEDIA_EXT) and "/app/creation/" not in cand and "thumb" not in low and "preview" not in low:
            return cand
    return None


async def _upload_image(session, png_bytes: bytes, status_cb) -> str:
    """Upload PNG bytes and return a creation identifier usable as a keyframe url.

    request_upload (presigned PUT target) -> HTTP PUT the raw bytes outside MCP ->
    finalize_upload (temp path -> hidden creation).
    """
    import requests

    if status_cb:
        status_cb("uploading image")
    text, js, err = await _call(session, "creations_request_upload", {"mimeType": "image/png"})
    if err:
        raise MCPError(f"creations_request_upload failed: {text[:400]}")
    # The presigned target is a plain JSON body; if `js` (structuredContent) doesn't
    # carry it, fall back to JSON parsed from the text block.
    payload = js if (isinstance(js, dict) and js.get("proxyUploadUrl")) else None
    if payload is None:
        try:
            payload = json.loads(text.strip())
        except Exception:  # noqa: BLE001
            payload = {}
    put_url = payload.get("proxyUploadUrl") or payload.get("uploadUrl") or payload.get("url")
    path = payload.get("path")
    if not put_url or not path:
        raise MCPError(f"request_upload missing proxyUploadUrl/path: {text[:400]}")

    def _put():
        r = requests.put(put_url, data=png_bytes,
                         headers={"Content-Type": "image/png"}, timeout=180)
        r.raise_for_status()

    # PUT is a blocking HTTP call outside MCP — run it off the event loop.
    await asyncio.get_event_loop().run_in_executor(None, _put)

    t2, j2, e2 = await _call(session, "creations_finalize_upload",
                             {"path": path, "visible": False})
    if e2:
        raise MCPError(f"creations_finalize_upload failed: {t2[:400]}")
    ident = _extract_identifier(j2, t2) or _asset_url(j2 or {})
    if not ident:
        raise MCPError(f"finalize_upload returned no identifier/url: {t2[:400]}")
    return ident


async def _op_video(session, slug, clip, start_url, end_url, start_bytes, end_bytes,
                    poll_interval, max_wait, status_cb):
    # Resolve keyframes: a URL wins; otherwise upload the tensor bytes to a creation.
    keyframes = dict(clip.get("keyframes") or {})
    for role, url, data in (("start", start_url, start_bytes), ("end", end_url, end_bytes)):
        ref = (url or "").strip() or (await _upload_image(session, data, status_cb) if data else "")
        if ref:
            keyframes[role] = {"type": "image", "url": ref}
    if keyframes:
        clip["keyframes"] = keyframes

    # Snapshot the newest video id *before* submitting so we can detect the new one.
    pre_ident = await _latest_video_identifier(session)

    text, js, err = await _call(session, "video_generate", {"video": {"clips": [clip]}})
    if err:
        raise MCPError(f"video_generate failed: {text[:500]}")
    # This MCP is UI-oriented: on a no-UI client video_generate replies only a
    # <system_reminder> and hides the identifier. Prefer an id in the response
    # (structuredContent / json), else recover the just-queued creation via search.
    ident = _extract_identifier(js, text)
    if not ident:
        ident = await _await_new_video_identifier(session, pre_ident, status_cb)
    if not ident:
        raise MCPError(
            "video_generate: could not resolve a creation identifier from the "
            f"response or creations_search. Response was: {text[:300]}"
        )
    if status_cb:
        status_cb(f"queued {ident}")
    deadline = time.time() + max_wait
    while time.time() < deadline:
        await asyncio.sleep(poll_interval)
        t2, j2, _e2 = await _call(session, "creations_get", {"creationIdentifier": ident})
        # creations_get replies key:value text (or json/structuredContent) — take the
        # view that actually carries a status/url.
        body = {}
        for cand in (j2, _parse_kv_text(t2)):
            if isinstance(cand, dict) and (_status_of(cand) or _asset_url(cand)):
                body = cand
                break
        status = _status_of(body)
        url = _asset_url(body)
        if status_cb:
            status_cb(f"{status or '...'} {ident}")
        if status in _FAIL:
            raise MCPError(f"creation {ident} failed (status={status})")
        if status in _DONE and url:
            return [url]
        if status in _DONE and not url:
            raise MCPError(f"creation {ident} done but no asset URL: {t2[:300]}")
    raise MCPTimeout(f"creation {ident} not finished after {max_wait:.0f}s")


# ── sync bridge ─────────────────────────────────────────────────────────────
def _run(make_coro):
    """Run an async coroutine to completion from sync code — even when this thread
    already has a running event loop.

    ComfyUI executes node functions *inside* an asyncio loop, so ``asyncio.run``
    (which forbids a nested run) raises "cannot be called from a running event
    loop". When a loop is already running we execute in a dedicated thread with its
    own fresh loop and block for the result; otherwise ``asyncio.run`` is fine.
    ``make_coro`` is a zero-arg callable returning a fresh coroutine (created inside
    the worker so it binds to that thread's loop).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())  # no running loop in this thread
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


# ── public sync API ───────────────────────────────────────────────────────
def authorize() -> list[str]:
    """Interactive one-time OAuth sign-in; returns the MCP tool names on success."""
    _require_mcp()
    holder = _start_callback_server(REDIRECT_PORT)
    try:
        async def _op(session):
            tools = await session.list_tools()
            return [t.name for t in tools.tools]
        return _run(lambda: _with_session(_op, interactive=True, holder=holder))
    finally:
        srv = holder.get("server")
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:  # noqa: BLE001
                pass


def generate_video(slug: str, clip: dict, *, start_url: str = "", end_url: str = "",
                   start_bytes: Optional[bytes] = None, end_bytes: Optional[bytes] = None,
                   poll_interval: float = 6.0, max_wait: float = 1800.0,
                   status_cb: Optional[Callable[[str], None]] = None) -> list[str]:
    """Submit a video_generate clip via the MCP, poll to completion, return URL(s).

    Keyframe images may be given as public URLs (`start_url`/`end_url`) or as raw PNG
    bytes (`start_bytes`/`end_bytes`) which are uploaded to a creation first. A URL
    takes precedence over bytes for the same role.
    """
    _require_mcp()
    if not has_tokens():
        raise MCPAuthError(
            "Magnific MCP not authorized. Run 'python authorize_magnific.py' in the "
            "ComfyUI-Magnific folder once to sign in."
        )
    return _run(lambda: _with_session(
        lambda s: _op_video(s, slug, clip, start_url, end_url, start_bytes, end_bytes,
                            poll_interval, max_wait, status_cb)
    ))


def download_to_output(url: str, prefix: str, ext_hint: str = ".mp4") -> str:
    """Download a result URL into ComfyUI's output dir; return the absolute path."""
    import os
    import requests

    try:
        import folder_paths  # type: ignore

        out_dir = Path(folder_paths.get_output_directory())
    except Exception:  # noqa: BLE001
        out_dir = PACK_DIR / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(url.split("?", 1)[0])[1].lower() or ext_hint
    stamp = time.strftime("%Y%m%d-%H%M%S")
    idx = 0
    while True:
        name = f"{prefix}_{stamp}{'' if idx == 0 else f'_{idx}'}{ext}"
        dest = out_dir / name
        if not dest.exists():
            break
        idx += 1
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"[ComfyUI-Magnific] Saved MCP result -> {dest}")
    return str(dest)
