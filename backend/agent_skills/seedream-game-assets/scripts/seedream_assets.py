"""Seedream (Volcengine Ark) sprite-sheet generation and grid cropping."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from collections import deque

from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "ep-20260513155556-gjcgg"
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_SIZE = "2K"
MAX_IMAGE_BYTES = 10_000_000
DEFAULT_MAX_ASSET_BYTES = 760_000
DEFAULT_MAX_CELL_EDGE = 1024
DEFAULT_THUMBNAIL_MAX_BYTES = 20_000
DEFAULT_THUMBNAIL_MAX_EDGE = 320


@dataclass(frozen=True)
class AssetSheetSpec:
    rows: int
    cols: int
    asset_names: list[str]
    cell_width: int | None = None
    cell_height: int | None = None
    transparent_background: bool | None = None

    def validate(self) -> None:
        if self.rows < 1 or self.cols < 1:
            raise ValueError("rows and cols must be >= 1")
        expected = self.rows * self.cols
        if len(self.asset_names) != expected:
            raise ValueError(
                f"asset_names length ({len(self.asset_names)}) must equal rows*cols ({expected})"
            )
        for name in self.asset_names:
            if not name.endswith(".png"):
                raise ValueError(f"asset name must end with .png: {name}")


def ark_client():
    from volcenginesdkarkruntime import Ark

    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("ARK_API_KEY is not set")
    return Ark(
        base_url=os.getenv("SEEDREAM_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
    )


def layout_hint(sheet: AssetSheetSpec) -> str:
    count = sheet.rows * sheet.cols
    if sheet.rows == 1 and sheet.cols == 1:
        layout = "single centered sprite"
    else:
        layout = f"{sheet.rows}x{sheet.cols} uniform grid ({count} cells)"
    names = ", ".join(sheet.asset_names)
    size_hint = ""
    if sheet.cell_width and sheet.cell_height:
        total_w = sheet.cell_width * sheet.cols
        total_h = sheet.cell_height * sheet.rows
        size_hint = (
            f" The sprite sheet MUST be exactly {total_w}x{total_h} pixels: "
            f"each grid cell is exactly {sheet.cell_width}x{sheet.cell_height} pixels."
        )
    return (
        f"One PNG sprite sheet only, {layout}, equal cell size, no gaps, cartoon game art."
        f" For gameplay sprites/icons/props, use a clean transparent background in every cell; "
        f"only thumbnails or full background images may be opaque. "
        f"Do not include letters, words, labels, captions, or UI text unless explicitly requested.{size_hint} "
        f"Cells left-to-right, top-to-bottom map to: {names}."
    )


def generate_sheet_image(*, prompt: str, sheet: AssetSheetSpec) -> tuple[bytes, tuple[int, int]]:
    sheet.validate()
    client = ark_client()
    full_prompt = f"{prompt.strip()}\n\n{layout_hint(sheet)}"
    model = os.getenv("SEEDREAM_MODEL", DEFAULT_MODEL)
    size = os.getenv("SEEDREAM_SIZE", DEFAULT_SIZE)

    logger.info("seedream generate model=%s size=%s grid=%sx%s", model, size, sheet.rows, sheet.cols)
    response = client.images.generate(
        model=model,
        prompt=full_prompt,
        sequential_image_generation="auto",
        response_format="url",
        output_format="png",
        size=size,
        stream=False,
        watermark=False,
    )
    if not response.data:
        raise RuntimeError("Seedream returned no images")
    item = response.data[0]
    url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
    if not url:
        raise RuntimeError("Seedream image has no url")
    with urlopen(url, timeout=120) as remote:
        raw = remote.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise RuntimeError(f"downloaded image exceeds {MAX_IMAGE_BYTES} bytes")
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    return raw, image.size


def crop_sheet(image: Image.Image, sheet: AssetSheetSpec) -> list[tuple[str, bytes]]:
    sheet.validate()
    width, height = image.size
    cell_w = width // sheet.cols
    cell_h = height // sheet.rows
    if cell_w < 1 or cell_h < 1:
        raise RuntimeError("image too small for grid crop")

    outputs: list[tuple[str, bytes]] = []
    index = 0
    for row in range(sheet.rows):
        for col in range(sheet.cols):
            left = col * cell_w
            top = row * cell_h
            right = width if col == sheet.cols - 1 else left + cell_w
            bottom = height if row == sheet.rows - 1 else top + cell_h
            cell = image.crop((left, top, right, bottom))
            asset_name = sheet.asset_names[index]
            if should_remove_background(sheet, asset_name):
                cell = remove_edge_background(cell)
            data = encode_png_under_limit(cell, asset_name=asset_name)
            outputs.append((asset_name, data))
            index += 1
    return outputs


def should_remove_background(sheet: AssetSheetSpec, asset_name: str) -> bool:
    if sheet.transparent_background is not None:
        return sheet.transparent_background
    return asset_name != "thumbnail.png"


def remove_edge_background(image: Image.Image, *, tolerance: int = 30) -> Image.Image:
    """Make edge-connected flat backgrounds transparent while preserving interior pixels."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width < 2 or height < 2:
        return rgba
    alpha = rgba.getchannel("A")
    if (alpha.getextrema()[0] or 0) < 250:
        return rgba

    pixels = rgba.load()
    corner_colors = [
        pixels[0, 0][:3],
        pixels[width - 1, 0][:3],
        pixels[0, height - 1][:3],
        pixels[width - 1, height - 1][:3],
    ]
    threshold = tolerance * tolerance * 3

    def close_to_corner(x: int, y: int) -> bool:
        r, g, b, a = pixels[x, y]
        if a < 8:
            return True
        for cr, cg, cb in corner_colors:
            if (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2 <= threshold:
                return True
        return False

    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        for y in (0, height - 1):
            if close_to_corner(x, y):
                queue.append((x, y))
                visited.add((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if (x, y) not in visited and close_to_corner(x, y):
                queue.append((x, y))
                visited.add((x, y))

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height or (nx, ny) in visited:
                continue
            if close_to_corner(nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny))

    if not visited:
        return rgba
    for x, y in visited:
        r, g, b, _ = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)
    return rgba


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def resize_to_max_edge(image: Image.Image, max_edge: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image
    scale = max_edge / float(longest)
    next_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(next_size, Image.Resampling.LANCZOS)


def encode_png(image: Image.Image, *, colors: int | None = None) -> bytes:
    source = image.convert("RGBA")
    buf = io.BytesIO()
    if colors:
        # Adaptive palette keeps game-card thumbnails small while retaining the
        # PNG contract expected by validation and generated-game asset loading.
        paletted = source.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        paletted.save(buf, format="PNG", optimize=True)
    else:
        source.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def encode_png_under_limit(image: Image.Image, *, asset_name: str) -> bytes:
    if asset_name == "thumbnail.png":
        max_bytes = env_int("SEEDREAM_THUMBNAIL_MAX_BYTES", DEFAULT_THUMBNAIL_MAX_BYTES)
        max_edge = env_int("SEEDREAM_THUMBNAIL_MAX_EDGE", DEFAULT_THUMBNAIL_MAX_EDGE)
    else:
        max_bytes = env_int("SEEDREAM_MAX_ASSET_BYTES", DEFAULT_MAX_ASSET_BYTES)
        max_edge = env_int("SEEDREAM_MAX_CELL_EDGE", DEFAULT_MAX_CELL_EDGE)
    working = resize_to_max_edge(image, max_edge)
    alpha = working.convert("RGBA").getchannel("A")
    has_transparency = (alpha.getextrema()[0] or 0) < 255

    palette_sizes = () if has_transparency else (128, 96, 64, 48, 32, 24, 16)
    best = encode_png(working, colors=None if has_transparency else 128)
    for colors in palette_sizes[1:]:
        if len(best) <= max_bytes:
            return best
        candidate = encode_png(working, colors=colors)
        if len(candidate) < len(best):
            best = candidate

    min_edge = 96 if asset_name == "thumbnail.png" else 256
    while len(best) > max_bytes and max(working.size) > min_edge:
        next_size = (max(1, int(working.width * 0.82)), max(1, int(working.height * 0.82)))
        working = working.resize(next_size, Image.Resampling.LANCZOS)
        candidates = [encode_png(working, colors=None)] if has_transparency else [
            encode_png(working, colors=colors) for colors in (96, 64, 48, 32, 24, 16)
        ]
        for candidate in candidates:
            if len(candidate) < len(best):
                best = candidate
            if len(candidate) <= max_bytes:
                return candidate

    if len(best) > max_bytes:
        raise RuntimeError(f"cropped asset {asset_name} exceeds {max_bytes} bytes after compression")
    logger.info("compressed asset %s to %d bytes size=%sx%s", asset_name, len(best), working.width, working.height)
    return best


def parse_sheet_specs(sheets: list[dict[str, Any]]) -> list[AssetSheetSpec]:
    specs: list[AssetSheetSpec] = []
    for entry in sheets:
        rows = int(entry.get("rows") or 0)
        cols = int(entry.get("cols") or 0)
        cell_width = entry.get("cellWidth") or entry.get("cell_width")
        cell_height = entry.get("cellHeight") or entry.get("cell_height")
        names = entry.get("assetNames") or entry.get("assets") or entry.get("asset_names") or []
        if not isinstance(names, list):
            raise ValueError("assetNames must be a list of filenames")
        specs.append(AssetSheetSpec(
            rows=rows,
            cols=cols,
            asset_names=[str(n) for n in names],
            cell_width=int(cell_width) if cell_width else None,
            cell_height=int(cell_height) if cell_height else None,
            transparent_background=entry.get("transparentBackground"),
        ))
    return specs


def generate_and_crop_assets(*, prompt: str, sheets: list[dict[str, Any]]) -> list[tuple[str, bytes]]:
    """Generate one sheet per spec; return (filename, png_bytes) pairs."""
    specs = parse_sheet_specs(sheets)
    if not specs:
        raise ValueError("sheets must contain at least one grid spec")
    all_assets: list[tuple[str, bytes]] = []
    for sheet in specs:
        raw, size = generate_sheet_image(prompt=prompt, sheet=sheet)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        logger.info("seedream sheet %sx%s downloaded as %sx%s", sheet.rows, sheet.cols, size[0], size[1])
        all_assets.extend(crop_sheet(image, sheet))
    return all_assets


def write_assets_to_dir(assets: list[tuple[str, bytes]], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for name, data in assets:
        path = output_dir / name
        path.write_bytes(data)
        saved.append(str(path))
    return saved


def asset_files_payload(assets: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    return [
        {
            "path": f"assets/{name}",
            "contentBase64": base64.b64encode(data).decode("ascii"),
            "mimeType": "image/png",
        }
        for name, data in assets
    ]


def load_spec_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("spec file must be a JSON object")
    return data
