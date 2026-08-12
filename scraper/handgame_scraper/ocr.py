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
