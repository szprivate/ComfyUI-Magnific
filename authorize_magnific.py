#!/usr/bin/env python
"""One-time Magnific MCP OAuth sign-in for the MagnificMCPVideo node.

Run this ONCE from the ComfyUI-Magnific folder, using the same Python that runs
ComfyUI (so `mcp` is available there):

    python authorize_magnific.py

It opens your browser to sign in to Magnific, captures the redirect on
http://localhost:8207/callback, and stores the OAuth tokens in ./.mcp_tokens/
(gitignored). The node then connects silently and refreshes the token as needed.
Re-run this if the node ever reports it needs re-authorization.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_client  # noqa: E402


def main() -> int:
    try:
        import mcp  # noqa: F401
    except Exception:
        print("ERROR: the 'mcp' package is not installed in this Python.\n"
              "       Install it here first:  pip install mcp")
        return 2

    print("Opening your browser to authorize Magnific (MCP)...")
    print("If it doesn't open, copy the URL printed below into your browser.\n")
    try:
        tools = mcp_client.authorize()
    except Exception as exc:  # noqa: BLE001
        print(f"\nAuthorization failed: {exc}")
        return 1
    print(f"\n✅ Authorized. {len(tools)} MCP tools available. Tokens saved in "
          f"{mcp_client.TOKEN_DIR}")
    print("You can now use the 'Magnific MCP Video' node in ComfyUI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
