"""Read the flyer.

Handgame flyers are images. The date, the location, the drum, the payout and
the phone number to call all live inside a JPEG, so without this module a
scraper collects pictures and no information.

Two engines:
  * Tesseract, always available, free, decent on plain text and poor on the
    heavily stylized display fonts flyers love.
  * Claude vision, optional, used when ANTHROPIC_API_KEY is set. Far better on
    real flyers because it reads layout, not just glyphs.

Tesseract runs first and its text is always kept for the reviewer to see.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps, ImageFilter

    _PIL = True
except ImportError:  # pragma: no cover
    _PIL = False

try:
    import pytesseract

    _TESS = True
except ImportError:  # pragma: no cover
    _TESS = False

try:
    import imagehash

    _IHASH = True
except ImportError:  # pragma: no cover
    _IHASH = False


def perceptual_hash(image_bytes: bytes) -> Optional[str]:
    """Hash that survives recompression and resizing.

    This is what catches the same flyer reposted on four different sites at
    four different resolutions.
    """
    if not (_PIL and _IHASH):
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return str(imagehash.phash(im.convert("RGB"), hash_size=16))
    except Exception as exc:
        log.debug("phash failed: %s", exc)
        return None


def _prep(im: "Image.Image") -> "Image.Image":
    """Upscale, grayscale and sharpen — measurably better OCR on flyers."""
    im = im.convert("L")
    w, h = im.size
    target = 2000
    if max(w, h) < target:
        scale = target / max(w, h)
        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    im = ImageOps.autocontrast(im)
    return im.filter(ImageFilter.SHARPEN)


def ocr_text(image_bytes: bytes) -> Optional[str]:
    """Plain Tesseract pass. Returns None when nothing legible comes back."""
    if not (_PIL and _TESS):
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            im = _prep(raw)
            best = ""
            # psm 6 (uniform block) handles most flyers. 4 (columns) and 11
            # (sparse text) are fallbacks for awkward layouts. Each pass on a
            # 2000px image is slow, so stop as soon as one reads well: a
            # usable flyer read has plenty of text and at least one number,
            # because every flyer prints a date.
            for psm in (6, 4, 11):
                try:
                    txt = pytesseract.image_to_string(im, config=f"--psm {psm}")
                except Exception:
                    continue
                if len(txt.strip()) > len(best.strip()):
                    best = txt
                if len(best.strip()) > 180 and any(c.isdigit() for c in best):
                    break
            text = re.sub(r"[ \t]+", " ", best)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return text or None
    except Exception as exc:
        log.debug("ocr failed: %s", exc)
        return None


VISION_PROMPT = """You are reading a flyer for a Native American handgame \
(also called stickgame, bone game, slahal, or lahal) event.

Return ONLY a JSON object, no prose, with these keys:
  title        - the event name as printed, or null
  start_date   - first day, "YYYY-MM-DD", or null
  end_date     - last day if it runs multiple days, else null
  location     - "City, State" if you can tell, otherwise the venue name, or null
  tribe        - the tribe, nation, or host group named, or null
  details      - one or two sentences: entry fee, payout, contact name and
                 phone, camping, drum, anything an attendee would need. Or null.
  is_handgame  - true only if this is genuinely a handgame/stickgame/bone game
                 event or a powwow that includes one
  year_printed - true if the flyer actually prints a year, false if you inferred it
  confidence   - 0.0 to 1.0, how sure you are of start_date and location

Rules: never invent a year that is not printed unless the context makes it \
unambiguous; if the flyer prints only a month and day, infer the next \
occurrence and set year_printed false. If the image is not an event flyer, \
set is_handgame false and everything else null."""


def vision_extract(
    image_bytes: bytes, media_type: str = "image/jpeg", model: str = "claude-opus-5"
) -> Optional[dict[str, Any]]:
    """Read a flyer with Claude vision. Returns None if unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import requests
    except ImportError:  # pragma: no cover
        return None

    # Shrink before upload: flyers are often 4000px scans and the API has limits.
    payload_bytes = image_bytes
    if _PIL:
        try:
            with Image.open(io.BytesIO(image_bytes)) as im:
                im = im.convert("RGB")
                if max(im.size) > 1568:
                    scale = 1568 / max(im.size)
                    im = im.resize(
                        (int(im.width * scale), int(im.height * scale)), Image.LANCZOS
                    )
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                payload_bytes = buf.getvalue()
                media_type = "image/jpeg"
        except Exception:
            pass

    body = {
        "model": model,
        "max_tokens": 900,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(payload_bytes).decode(),
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
    }
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=90,
        )
        if resp.status_code != 200:
            log.warning("vision API %s: %s", resp.status_code, resp.text[:200])
            return None
        text = "".join(
            blk.get("text", "") for blk in resp.json().get("content", [])
        ).strip()
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        return json.loads(match.group(0))
    except Exception as exc:
        log.warning("vision extraction failed: %s", exc)
        return None


def _longest_run(flags: list[bool]) -> tuple[int, int]:
    """Start and end of the longest unbroken stretch of True."""
    best = (0, 0)
    start: Optional[int] = None
    for i, on in enumerate(flags + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def strip_screenshot_chrome(image_bytes: bytes) -> tuple[bytes, Optional[str]]:
    """Cut the phone and browser furniture off a screenshot of a flyer.

    Flyers arrive as phone screenshots far more often than as clean images,
    because that is how you save one off Facebook. They carry a status bar, an
    address bar reading facebook.com, a nav bar, black letterboxing, and
    sometimes a stray UI button — none of which belong on a public calendar.

    Detection is deliberately narrow: a band of rows at the very top or bottom
    that are each a single flat colour all the way across. Real flyer artwork
    almost never does that, and designed headers carry type, which breaks the
    flatness. Nothing is cropped unless such a band is found, so an ordinary
    photographed or exported flyer passes through untouched.

    Returns (bytes, note). The note is None when nothing was changed.
    """
    if not _PIL:
        return image_bytes, None
    try:
        im = Image.open(io.BytesIO(image_bytes))
        fmt = (im.format or "PNG").upper()
        im = im.convert("RGB")
        w, h = im.size
        if w < 200 or h < 200:
            return image_bytes, None

        def run_from(y0: int, step: int) -> tuple[int, tuple[int, int, int]]:
            """How far one edge colour continues, and what that colour is."""
            edge = im.getpixel((0, y0))
            n, y = 0, y0
            while 0 <= y < h:
                c = im.getpixel((0, y))
                if any(abs(c[i] - edge[i]) > 12 for i in (0, 1, 2)):
                    break
                n += 1
                y += step
            return n, edge

        def is_ui_colour(c: tuple[int, int, int]) -> bool:
            """Chrome is a brand colour. Letterboxing is black or white.

            This is the whole discriminator, and it came from measuring the
            real files. Every browser band seen so far is (39, 25, 72) — a
            definite purple. Every false crop in testing was a band of pure
            black or pure white: a flyer's own letterbox, matte or border.
            Requiring some actual hue keeps artwork safe, at the cost of
            missing a browser whose chrome is white or black. Missing one is
            a screenshot with a status bar on the calendar; the other way
            round is a flyer with its top sliced off.
            """
            return max(c) - min(c) > 25

        # A status bar plus an address bar is a substantial slab — 309 rows,
        # 12% of the image, on the flyers that prompted this. A thin flat edge
        # is artwork: the Kainai flyer ends in a 16-row dark band, and an
        # earlier version of this cut 119 rows off the bottom of it.
        min_band = max(40, h // 25)

        top, top_colour = run_from(0, 1)
        if top < min_band or not is_ui_colour(top_colour):
            return image_bytes, None

        bottom_run, bottom_colour = run_from(h - 1, -1)
        bottom = h
        if bottom_run >= min_band and is_ui_colour(bottom_colour):
            bottom = h - bottom_run
        if top >= bottom:
            return image_bytes, None

        body = im.crop((0, top, w, bottom))
        # Within the page, take the largest solid block of content. That drops
        # the black letterboxing above and below the image, and also a lone UI
        # button sitting in the letterbox, which a plain bounding box keeps.
        mask = body.convert("L").point(lambda v: 255 if v > 14 else 0)
        bw, bh = mask.size
        step = 3
        rows = [
            sum(1 for x in range(0, bw, step) if mask.getpixel((x, y)))
            / max(1, bw / step)
            for y in range(bh)
        ]
        y0, y1 = _longest_run([d > 0.05 for d in rows])
        if y1 - y0 < 50:
            y0, y1 = 0, bh
        cols = [
            sum(1 for y in range(y0, y1, step) if mask.getpixel((x, y)))
            / max(1, (y1 - y0) / step)
            for x in range(bw)
        ]
        x0, x1 = _longest_run([d > 0.05 for d in cols])
        if x1 - x0 < 50:
            x0, x1 = 0, bw
        out = body.crop((x0, y0, x1, y1))

        # Refuse a crop that ate the flyer. Better to publish a screenshot with
        # a status bar than a sliver of one.
        if out.width * out.height < (w * h) * 0.15:
            return image_bytes, None

        buf = io.BytesIO()
        out.save(buf, "PNG" if fmt not in ("JPEG", "PNG") else fmt, optimize=True)
        return buf.getvalue(), f"cropped {w}x{h} screenshot to {out.width}x{out.height}"
    except Exception as exc:  # noqa: BLE001
        log.warning("could not crop %s; using it as-is", exc)
        return image_bytes, None
