"""Discord application icons for detected games, cached on disk.

Looks a game up by name in Discord's detectable-games list, fetches the
application's icon hash, and returns a CDN URL. Never blocks: network work
runs in a background thread, and callers get None until the result is cached.
"""
import json
import threading
import time
import urllib.request
from pathlib import Path

_API = "https://discord.com/api/v10"
_CACHE_DIR = Path.home() / ".cache" / "vice-flare"
_ICONS = _CACHE_DIR / "icons.json"
_LIST = _CACHE_DIR / "detectable.json"
_LIST_TTL = 7 * 86400
_HEADERS = {"User-Agent": "Mozilla/5.0 (flare)"}
_lock = threading.Lock()
_inflight = set()


def _get(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.load(resp)


def _load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path, data):
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError:
        pass


def _name_map():
    cached = _load(_LIST, {})
    if cached.get("names") and cached.get("ts", 0) + _LIST_TTL > time.time():
        return cached["names"]
    try:
        apps = _get(f"{_API}/applications/detectable")
    except Exception:
        return cached.get("names", {})
    names = {}
    for a in apps:
        n = str(a.get("name", "")).strip().lower()
        if n and n not in names and a.get("id"):
            names[n] = a["id"]
    _save(_LIST, {"ts": time.time(), "names": names})
    return names


def _resolve(key):
    try:
        names = _name_map()
        if not names:
            return  # list unavailable; try again later, don't cache a miss
        app_id = names.get(key)
        url = ""
        if app_id:
            icon = _get(f"{_API}/applications/{app_id}/rpc").get("icon")
            if icon:
                url = f"https://cdn.discordapp.com/app-icons/{app_id}/{icon}.png"
    except Exception:
        return  # transient failure; don't cache
    with _lock:
        icons = _load(_ICONS, {})
        icons[key] = url
        _save(_ICONS, icons)


def discord_icon_url(game):
    """Cached icon URL for a game name, or None (and starts a lookup)."""
    key = (game or "").strip().lower()
    if not key:
        return None
    icons = _load(_ICONS, {})
    if key in icons:
        return icons[key] or None
    with _lock:
        if key in _inflight:
            return None
        _inflight.add(key)

    def run():
        try:
            _resolve(key)
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=run, daemon=True).start()
    return None
