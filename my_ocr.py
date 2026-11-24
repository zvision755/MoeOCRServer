"""MoeTranslate-compatible Japanese screenshot translation backend."""
import base64
import binascii
import hmac
import logging
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock

import requests
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from ocrmac import ocrmac
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

app = FastAPI(title="MoeOCRServer", version="0.1.0")
logger = logging.getLogger(__name__)
LOG_DIR = Path(__file__).resolve().parent / "logs"
log_filename = LOG_DIR / f"translation_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
log_lock = Lock()
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
NIUTRANS_URL = "https://api.niutrans.com/NiuTransServer/translation"


class ImageRequest(BaseModel):
    img: str
    source: str = "ja"
    target: str = "zh"


def recognize_image(encoded: str) -> str:
    if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 16:
        raise HTTPException(413, "Image too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image too large")
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "Image dimensions too large")
            rgb = image.convert("RGB")
        annotations = ocrmac.OCR(rgb, language_preference=["ja-JP"]).recognize()
        return "".join(item[0] for item in annotations).strip()
    except (ValueError, binascii.Error, UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise HTTPException(400, "Invalid image") from None


def translate_text(raw_text: str) -> str:
    api_key = os.environ.get("NIUTRANS_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Translation API key is not configured")
    try:
        response = requests.post(
            NIUTRANS_URL,
            data={"from": "ja", "to": "zh", "apikey": api_key, "src_text": raw_text},
            timeout=(5, 30),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError("Unexpected status")
        text = response.json().get("tgt_text")
        if not isinstance(text, str):
            raise ValueError("Missing translation")
        return text
    except (requests.RequestException, ValueError, AttributeError):
        logger.warning("Translation provider request failed")
        raise HTTPException(502, "Translation provider failed") from None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/translate")
def handle_request(data: ImageRequest, authorization: str | None = Header(default=None)):
    token = os.environ.get("MOE_SERVER_TOKEN", "")
    if token and not hmac.compare_digest(
        (authorization or "").encode(), f"Bearer {token}".encode()
    ):
        raise HTTPException(401, "Unauthorized")
    if (data.source, data.target) != ("ja", "zh"):
        raise HTTPException(400, "Only ja to zh is supported")
    raw_text = recognize_image(data.img)
    if not raw_text:
        return {"translation": ""}
    final_text = translate_text(raw_text)
    if os.environ.get("MOE_LOG_TRANSLATIONS", "0") == "1":
        with log_lock:
            LOG_DIR.mkdir(mode=0o700, exist_ok=True)
            with log_filename.open("a", encoding="utf-8") as log:
                log.write(f"{raw_text}\n{final_text}\n\n")
    return {"translation": final_text}


if __name__ == "__main__":
    host = os.environ.get("MOE_HOST", "127.0.0.1")
    port = int(os.environ.get("MOE_PORT", "8000"))
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("MOE_SERVER_TOKEN"):
        raise SystemExit("Set MOE_SERVER_TOKEN before binding outside localhost.")
    uvicorn.run(app, host=host, port=port)
