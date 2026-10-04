"""
Square (1080x1080) ad images for the Meta catalog.

Auction photos are landscape (~4:3). Meta shows carousel cards as 1:1, so it
letterboxes them with empty grey bars. This module renders a branded square
instead: title band on top, the photo in the middle, price band at the bottom.

Rendered files are named <lot_id>-<hash>.jpg, where the hash covers the photo
URL, title, price and TEMPLATE_VERSION. When any of those changes the URL
changes too, so Meta re-downloads the image instead of serving a stale cached
copy with an old price.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import random
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

TEMPLATE_VERSION = "4"   # bump to force every image to re-render

SIZE = 1080
TOP_H = 140              # title band
BOTTOM_H = 130           # price band
PHOTO_H = SIZE - TOP_H - BOTTOM_H   # 810 → exactly 4:3 at full width
MARGIN = 44

BG = (21, 23, 28)
WHITE = (255, 255, 255)
MUTED = (165, 170, 180)
RED = (190, 30, 35)

FONT_DIR = Path(__file__).parent / "fonts"
BOLD = str(FONT_DIR / "NotoSansGeorgian-Bold.ttf")
HEAVY = str(FONT_DIR / "NotoSansGeorgian-ExtraBold.ttf")
REGULAR = str(FONT_DIR / "NotoSansGeorgian-Regular.ttf")

# location line (Mtavruli capitals), shown with a map-pin icon
PLACE = "ᲬᲔᲠᲝᲕᲐᲜᲘ"
PLACE_SUB = "ᲚᲐᲘᲝᲜ ᲐᲣᲥᲪᲘᲝᲜᲘᲡ ᲐᲕᲢᲝᲡᲐᲓᲒᲝᲛᲘ"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, path: str,
              max_w: int, start: int, min_size: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > min_size:
        f = _font(path, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(path, min_size)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _photo_block(photo: Image.Image) -> Image.Image:
    """Fill a SIZE x PHOTO_H block with the photo without empty bars."""
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    target = SIZE / PHOTO_H
    ratio = photo.width / photo.height
    if 0.85 * target <= ratio <= 1.25 * target:
        # close to 4:3 → crop to fill, losing at most a thin strip
        return ImageOps.fit(photo, (SIZE, PHOTO_H), Image.LANCZOS, centering=(0.5, 0.5))
    # very different shape → whole photo on a blurred copy of itself
    bg = ImageOps.fit(photo, (SIZE, PHOTO_H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, BG), 0.35)
    fg = ImageOps.contain(photo, (SIZE, PHOTO_H), Image.LANCZOS)
    bg.paste(fg, ((SIZE - fg.width) // 2, (PHOTO_H - fg.height) // 2))
    return bg


def _pin(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Map-pin icon centred on (cx, cy): round head with a hole, pointed tail."""
    head_cy = cy - r * 0.45
    tip = (cx, cy + r * 1.35)
    d.polygon([(cx - r * 0.82, head_cy + r * 0.45), (cx + r * 0.82, head_cy + r * 0.45), tip], fill=RED)
    d.ellipse([cx - r, head_cy - r, cx + r, head_cy + r], fill=RED)
    h = r * 0.42
    d.ellipse([cx - h, head_cy - h, cx + h, head_cy + h], fill=BG)


def render(photo: Image.Image, title: str, price_usd: int, price_label: str) -> Image.Image:
    canvas = Image.new("RGB", (SIZE, SIZE), BG)
    canvas.paste(_photo_block(photo), (0, TOP_H))
    d = ImageDraw.Draw(canvas)

    # --- top band: title ---
    max_w = SIZE - 2 * MARGIN
    tf = _fit_font(d, title, BOLD, max_w, 64, 40)
    t = _ellipsize(d, title, tf, max_w)
    d.text((SIZE // 2, TOP_H // 2), t, font=tf, fill=WHITE, anchor="mm")

    # --- bottom band: price pill + brand ---
    y0 = TOP_H + PHOTO_H
    cy = y0 + BOTTOM_H // 2
    label_f = _font(REGULAR, 24)
    price_f = _font(HEAVY, 54 if price_label else 62)
    price_txt = f"${price_usd:,}"
    pw = int(max(d.textlength(price_txt, font=price_f),
                 d.textlength(price_label, font=label_f) if price_label else 0))
    pad = 20 if price_label else 30
    pill = [MARGIN - 6, y0 + 14, MARGIN + pw + 2 * pad - 6, y0 + BOTTOM_H - 14]
    d.rounded_rectangle(pill, radius=18, fill=RED)
    px = MARGIN + 14
    if price_label:
        d.text((px, pill[1] + 6), price_label, font=label_f, fill=(255, 225, 225), anchor="la")
        d.text((px, pill[3] - 14), price_txt, font=price_f, fill=WHITE, anchor="ls")
    else:
        d.text(((pill[0] + pill[2]) // 2, (pill[1] + pill[3]) // 2), price_txt,
               font=price_f, fill=WHITE, anchor="mm")

    place_f = _font(HEAVY, 40)
    sub_f = _font(BOLD, 21)
    rx = SIZE - MARGIN
    text_w = int(max(d.textlength(PLACE, font=place_f), d.textlength(PLACE_SUB, font=sub_f)))
    tx = rx - text_w                       # left edge of the text block
    d.text((tx, cy + 2), PLACE, font=place_f, fill=WHITE, anchor="ls")
    d.text((tx, cy + 14), PLACE_SUB, font=sub_f, fill=MUTED, anchor="lt")
    _pin(d, tx - 22 - 22, cy, 22)
    return canvas


def image_key(lot_id: str, src: str, title: str, price: int, label: str) -> str:
    h = hashlib.sha1(f"{TEMPLATE_VERSION}|{src}|{title}|{price}|{label}".encode()).hexdigest()[:10]
    safe_id = "".join(c for c in str(lot_id) if c.isalnum()) or "x"
    return f"{safe_id}-{h}.jpg"


async def _download(client: httpx.AsyncClient, url: str, attempts: int = 4) -> bytes | None:
    for a in range(1, attempts + 1):
        try:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                return r.content
            if r.status_code in (404, 410):
                return None
        except Exception:
            pass
        await asyncio.sleep(min(30.0, 2.0 ** a) + random.uniform(0, 1))
    return None


async def build_images(
    client: httpx.AsyncClient,
    jobs: list[dict[str, Any]],
    cache_dir: Path,
    out_dir: Path,
    concurrency: int = 4,
) -> dict[str, str]:
    """
    jobs: dicts with lot_id, src, title, price, label.
    Returns {lot_id: filename} for every image available in out_dir.
    Already-rendered images are reused from cache_dir; only new or changed
    listings are downloaded and rendered.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    result: dict[str, str] = {}
    stats = {"cached": 0, "rendered": 0, "failed": 0}

    async def one(job: dict[str, Any]) -> None:
        name = image_key(job["lot_id"], job["src"], job["title"], job["price"], job["label"])
        cached = cache_dir / name
        if not cached.exists():
            async with sem:
                data = await _download(client, job["src"])
            if not data:
                stats["failed"] += 1
                return
            try:
                img = await asyncio.to_thread(
                    lambda: render(Image.open(io.BytesIO(data)), job["title"], job["price"], job["label"])
                )
                tmp = cached.with_suffix(".tmp")
                await asyncio.to_thread(img.save, tmp, "JPEG", quality=86, optimize=True, progressive=True)
                tmp.replace(cached)
            except Exception as e:
                stats["failed"] += 1
                print(f"[warn] image {job['lot_id']}: {type(e).__name__}: {e}", file=sys.stderr)
                return
            stats["rendered"] += 1
        else:
            stats["cached"] += 1
        shutil.copyfile(cached, out_dir / name)
        result[str(job["lot_id"])] = name

    await asyncio.gather(*(one(j) for j in jobs))

    # drop cache entries for cars no longer in the feed, and versions
    # superseded by a fresh render (old price/photo). Lots whose download
    # failed this run keep their old file in case it's needed later.
    active_ids = {"".join(c for c in str(j["lot_id"]) if c.isalnum()) for j in jobs}
    keep = set(result.values())
    current_by_id = {n.rsplit("-", 1)[0]: n for n in keep}
    for f in cache_dir.glob("*.jpg"):
        lot = f.name.rsplit("-", 1)[0]
        if lot not in active_ids or (lot in current_by_id and f.name != current_by_id[lot]):
            f.unlink(missing_ok=True)

    print(f"[info] ad images: {stats}", file=sys.stderr)
    return result
