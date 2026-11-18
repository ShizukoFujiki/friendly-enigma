"""Private document intake service. Uploads are disabled unless explicitly configured."""
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import logging
import os
from pathlib import Path
import shutil
import smtplib
import ssl
import subprocess
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, File, Form, HTTPException, Request as WebRequest, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", "/var/lib/sunriver-intake/submissions")).resolve()
TEMP_ROOT = Path(os.environ.get("TMPDIR", "/var/lib/sunriver-intake/tmp")).resolve()
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 5
MAX_REQUEST_BYTES = 25 * 1024 * 1024
RATE_LIMIT_COUNT = 5
RATE_LIMIT_SECONDS = 60 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sunriver-intake")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
hits = defaultdict(deque)


def cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def upload_configured() -> bool:
    required = (
        "PUBLIC_ORIGIN", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY",
        "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "NOTIFY_TO",
    )
    return cfg("ENABLE_UPLOADS") == "1" and all(cfg(k) for k in required) and shutil.which("clamdscan") is not None


def check_private_paths() -> None:
    if ROOT == UPLOAD_ROOT or ROOT in UPLOAD_ROOT.parents:
        raise RuntimeError("UPLOAD_DIR must be outside the application directory.")
    UPLOAD_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    TEMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(UPLOAD_ROOT, 0o700)
    os.chmod(TEMP_ROOT, 0o700)


@app.on_event("startup")
async def startup() -> None:
    if cfg("ENABLE_UPLOADS") == "1":
        check_private_paths()
        if not shutil.which("clamdscan"):
            raise RuntimeError("clamdscan is required when uploads are enabled.")
        if not upload_configured():
            raise RuntimeError("Upload configuration is incomplete; refusing to start enabled intake.")


@app.get("/")
async def home():
    return FileResponse(INDEX, media_type="text/html")


@app.get("/api/config")
async def public_config():
    enabled = upload_configured()
    return {
        "enabled": enabled,
        "siteKey": cfg("TURNSTILE_SITE_KEY") if enabled else "",
        "maxFileBytes": MAX_FILE_BYTES,
        "maxFiles": MAX_FILES,
    }


def verify_turnstile(token: str, remote_ip: str | None) -> bool:
    data = {
        "secret": cfg("TURNSTILE_SECRET_KEY"),
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip
    req = Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=urlencode(data).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=8) as response:
            result = json.loads(response.read(16_384))
        return bool(result.get("success"))
    except Exception:
        log.warning("Turnstile verification failed")
        return False


def allow_rate(remote_ip: str) -> bool:
    now = asyncio.get_running_loop().time()
    q = hits[remote_ip]
    while q and now - q[0] > RATE_LIMIT_SECONDS:
        q.popleft()
    if len(q) >= RATE_LIMIT_COUNT:
        return False
    q.append(now)
    return True


def identify_media(header: bytes) -> tuple[str, str] | None:
    if header[:1024].find(b"%PDF-") >= 0:
        return "application/pdf", ".pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    return None


def scan_file(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["clamdscan", "--no-summary", str(path)],
            check=False, capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def send_notification(reference: str) -> bool:
    message = EmailMessage()
    message["Subject"] = "New document submission received"
    message["From"] = cfg("SMTP_FROM")
    message["To"] = cfg("NOTIFY_TO")
    message.set_content(
        "A new document submission was received.\n"
        f"Reference: {reference}\n"
        "Sign in to the server through the approved staff process to retrieve it."
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg("SMTP_HOST"), int(cfg("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(cfg("SMTP_USERNAME"), cfg("SMTP_PASSWORD"))
            smtp.send_message(message)
        return True
    except Exception:
        log.error("Notification delivery failed for submission reference %s", reference)
        return False


@app.post("/api/submissions")
async def create_submission(
    request: WebRequest,
    documents: list[UploadFile] = File(...),
    website: str = Form(""),
    cf_turnstile_response: str = Form(""),
):
    if not upload_configured():
        raise HTTPException(status_code=503, detail="Document submission is not available.")
    expected_origin = cfg("PUBLIC_ORIGIN").rstrip("/")
    if request.headers.get("origin", "").rstrip("/") != expected_origin:
        raise HTTPException(status_code=403, detail="Request could not be accepted.")
    if website:
        raise HTTPException(status_code=400, detail="Request could not be accepted.")
    client_ip = request.client.host if request.client else ""
    if not allow_rate(client_ip):
        raise HTTPException(status_code=429, detail="Please wait before trying again.")
    if not verify_turnstile(cf_turnstile_response, client_ip):
        raise HTTPException(status_code=400, detail="Please complete the verification and try again.")
    if not documents or len(documents) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Select between 1 and {MAX_FILES} files.")

    reference = uuid.uuid4().hex
    submission_dir = UPLOAD_ROOT / reference
    submission_dir.mkdir(mode=0o700)
    total = 0
    saved: list[dict[str, str]] = []
    try:
        for index, upload in enumerate(documents, start=1):
            first = await upload.read(1024)
            media = identify_media(first)
            if media is None:
                raise HTTPException(status_code=415, detail="Only PDF, JPG, and PNG files are accepted.")
            mime, suffix = media
            target = submission_dir / f"{index:02d}{suffix}"
            size = len(first)
            if size > MAX_FILE_BYTES or total + size > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="The selected files exceed the upload limit.")
            with target.open("xb") as out:
                os.chmod(target, 0o600)
                out.write(first)
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE_BYTES or total + size > MAX_REQUEST_BYTES:
                        raise HTTPException(status_code=413, detail="The selected files exceed the upload limit.")
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            total += len(first)
            if not scan_file(target):
                raise HTTPException(status_code=422, detail="A selected file could not pass the security scan.")
            saved.append({"file": target.name, "type": mime, "bytes": str(size)})

        manifest = {
            "reference": reference,
            "received_utc": datetime.now(timezone.utc).isoformat(),
            "files": saved,
        }
        meta = submission_dir / "submission.json"
        with meta.open("x", encoding="utf-8") as out:
            os.chmod(meta, 0o600)
            json.dump(manifest, out)
            out.flush()
            os.fsync(out.fileno())
    except HTTPException:
        shutil.rmtree(submission_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(submission_dir, ignore_errors=True)
        log.exception("Submission failed before completion")
        raise HTTPException(status_code=500, detail="Submission could not be completed.")
    finally:
        for upload in documents:
            await upload.close()

    if not send_notification(reference):
        # Keep the files private and retrievable; the server log contains the reference for follow-up.
        log.error("Submission stored; notification needs retry. Reference %s", reference)
    else:
        log.info("Submission received. Reference %s", reference)
    return JSONResponse({"ok": True, "reference": reference}, status_code=201)


app.mount("/assets", StaticFiles(directory=ROOT / "assets", check_dir=False), name="assets")
