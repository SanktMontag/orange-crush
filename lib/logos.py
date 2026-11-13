"""Optional team logos.

Drop an image into ``assets/logos/teams/`` named after the team, for example
``mighty-moose.png``, or after its team_id, for example ``2.png``. PNG, JPG,
WEBP and SVG all work. Teams without a file simply show no logo.
"""

from __future__ import annotations

import base64
import io
import re
from functools import lru_cache
from pathlib import Path

from lib.db import TEAM_ID

LOGO_DIR = Path(__file__).resolve().parents[1] / "assets" / "logos"
TEAM_LOGO_DIR = LOGO_DIR / "teams"
CRUSH_LOGO = LOGO_DIR / "Crush_Round_Orange_30_Clean.png"
EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".svg")


def slugify(name: str) -> str:
    """'Rainier Reindeers HC-9' -> 'rainier-reindeers-hc-9'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def logo_path(team_id: int, team_name: str) -> Path | None:
    """Return the logo file for a team, or None if there isn't one."""
    for stem in (slugify(team_name), str(team_id)):
        for extension in EXTENSIONS:
            candidate = TEAM_LOGO_DIR / f"{stem}{extension}"
            if candidate.is_file():
                return candidate
    if team_id == TEAM_ID and CRUSH_LOGO.is_file():
        return CRUSH_LOGO
    return None


@lru_cache(maxsize=64)
def _data_uri(path: str, modified: float) -> str:
    source = Path(path)
    if source.suffix.lower() == ".svg":
        encoded = base64.b64encode(source.read_bytes()).decode()
        return f"data:image/svg+xml;base64,{encoded}"

    from PIL import Image

    with Image.open(source) as image:
        image = image.convert("RGBA")
        image.thumbnail((96, 96))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def logo_data_uri(team_id: int, team_name: str) -> str | None:
    """A small inline copy of the team's logo, for embedding in charts."""
    path = logo_path(team_id, team_name)
    if path is None:
        return None
    return _data_uri(str(path), path.stat().st_mtime)
