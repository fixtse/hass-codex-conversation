"""Codex CLI release used as the backend protocol compatibility baseline."""

CODEX_CLIENT_VERSION = "0.160.1"
CODEX_HEADERS = {
    "originator": "codex_cli_rs",
    "User-Agent": f"hass-codex-conversation (codex/{CODEX_CLIENT_VERSION})",
}
