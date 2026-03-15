import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scanner import ES2_STATUS, Scanner, ScanSettings

# ─── Paths ────────────────────────────────────────────────────────────────────
# Use .resolve() so BASE_DIR is always absolute, regardless of how Python
# sets __file__ (relative vs absolute) when imported by uvicorn.
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
BATCHES_DIR = BASE_DIR / "batches"
SETTINGS_FILE = BASE_DIR / "settings.json"
CONFIG_FILE = BASE_DIR / "config.json"
INDEX_FILE = BATCHES_DIR / "index.json"
BATCHES_DIR.mkdir(exist_ok=True)

# Validate settings.json at startup — fail fast with a clear message.
if not SETTINGS_FILE.exists():
    raise SystemExit(f"[error] settings.json not found at: {SETTINGS_FILE}")
try:
    json.loads(SETTINGS_FILE.read_text())
except json.JSONDecodeError as _e:
    raise SystemExit(f"[error] settings.json is not valid JSON ({SETTINGS_FILE}): {_e}")

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="HeadlessScan API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=1)
_scanner = Scanner(str(SETTINGS_FILE))
_active_task: Optional[asyncio.Task] = None
_ws_clients: Set[WebSocket] = set()

# ─── Auto-scan state ─────────────────────────────────────────────────────────
_autoscan_enabled: bool = False
_autoscan_task: Optional[asyncio.Task] = None
_autoscan_settings: ScanSettings = ScanSettings()

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
# Allow letters, digits, spaces, underscores, hyphens, periods.
# Must start with a letter, digit, or underscore (not a space or dot).
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9 _\-.]*$")


# ─── Pydantic models ──────────────────────────────────────────────────────────
class ScanRequest(BaseModel):
    timeout: float = 10.0
    format: str = "pdf"
    dpi: Optional[int] = None
    duplex: bool = False
    blank_page_skip: bool = False
    output_dir: str = ""
    webhook_url: str = ""


class RenameRequest(BaseModel):
    name: str


# ─── Index helpers ────────────────────────────────────────────────────────────
def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"batches": []}


def _save_index(index: dict) -> None:
    INDEX_FILE.write_text(json.dumps(index, indent=2))


_CONFIG_DEFAULTS = {
    "format": "pdf",
    "timeout": 10,
    "dpi": 300,
    "duplex": False,
    "blank_page_skip": False,
    "output_dir": "",
    "webhook_url": "",
    "autostart_autoscan": False,
}


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text())
            # Merge with defaults so missing keys are always present
            return {**_CONFIG_DEFAULTS, **{k: v for k, v in raw.items() if not k.startswith('_')}}
        except json.JSONDecodeError:
            pass
    return dict(_CONFIG_DEFAULTS)


# ─── WebSocket broadcast ──────────────────────────────────────────────────────
async def _broadcast(payload: dict) -> None:
    text = json.dumps(payload)
    dead: Set[WebSocket] = set()
    for ws in list(_ws_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


# ─── Webhook helper ──────────────────────────────────────────────────────────
def _fire_webhook(url: str, payload: dict) -> None:
    """POST JSON payload to the webhook URL. Runs in a thread; errors are logged to stderr."""
    if not url:
        return
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:
        print(f"[webhook] POST to {url!r} failed: {exc}")


# ─── epsonscan2 one-shot subprocess (used by both manual and auto-scan) ────────
def _epsonscan2(tmp_config: pathlib.Path) -> bytes:
    proc = subprocess.Popen(
        ["epsonscan2", "-s", str(tmp_config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stdout, _ = proc.communicate()
    return stdout


# ─── Scan background task ─────────────────────────────────────────────────────
async def _scan_task(batch_id: str, settings: ScanSettings) -> None:
    global _active_task
    loop = asyncio.get_running_loop()
    batch_dir = BATCHES_DIR / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    def log(level: str, message: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast(
                {
                    "type": "log",
                    "level": level,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            loop,
        )

    # Register batch in index before starting
    now = datetime.now()
    batch_ts = now.strftime("%Y%m%d_%H%M%S")
    index = _load_index()
    index["batches"].insert(
        0,
        {
            "id": batch_id,
            "name": f"batch_{batch_ts}",
            "created_at": now.isoformat(),
            "status": "scanning",
            "pages": 0,
            "format": settings.format,
            "output_dir": settings.output_dir,
            "files": [],
        },
    )
    _save_index(index)

    await _broadcast({"type": "batch_created", "batch_id": batch_id})
    await _broadcast(
        {
            "type": "log",
            "level": "info",
            "message": f"Starting scan batch {batch_id[:8]}...",
            "timestamp": datetime.now().isoformat(),
        }
    )

    try:
        result = await loop.run_in_executor(
            _executor, lambda: _scanner.run(settings, batch_dir, log, batch_ts)
        )
    except Exception as exc:
        result = {"success": False, "pages": 0, "files": []}
        await _broadcast(
            {
                "type": "log",
                "level": "error",
                "message": f"Scan exception: {exc}",
                "timestamp": datetime.now().isoformat(),
            }
        )

    # Copy files to output_dir if specified and scan succeeded
    final_files = result.get("files", [])
    if result["success"] and settings.output_dir:
        dest = pathlib.Path(settings.output_dir)
        try:
            dest.mkdir(parents=True, exist_ok=True)
            for fname in final_files:
                shutil.copy2(batch_dir / fname, dest / fname)
            log("info", f"Files saved to {dest}")
            # Remove local batch storage — files live in output_dir
            shutil.rmtree(batch_dir, ignore_errors=True)
            final_files = [str(dest / f) for f in final_files]
        except Exception as exc:
            log("warning", f"Could not copy to output directory: {exc}")

    # Update index with final result
    index = _load_index()
    for batch in index["batches"]:
        if batch["id"] == batch_id:
            batch["status"] = "done" if result["success"] else "failed"
            batch["pages"] = result.get("pages", 0)
            batch["files"] = final_files
            break
    _save_index(index)

    await _broadcast(
        {
            "type": "scan_complete",
            "batch_id": batch_id,
            "success": result["success"],
            "pages": result.get("pages", 0),
            "status": "done" if result["success"] else "failed",
            "files": final_files,
        }
    )
    if settings.webhook_url:
        await loop.run_in_executor(
            None,
            lambda: _fire_webhook(settings.webhook_url, {
                "event": "scan_complete",
                "batch_id": batch_id,
                "success": result["success"],
                "pages": result.get("pages", 0),
                "files": final_files,
            }),
        )
    _active_task = None


# ─── Auto-scan loop ──────────────────────────────────────────────────────────
async def _autoscan_loop() -> None:
    global _autoscan_enabled, _autoscan_task
    loop = asyncio.get_running_loop()

    def log(level: str, message: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "log", "level": level, "message": message,
                        "timestamp": datetime.now().isoformat()}),
            loop,
        )

    log("info", "Auto-scan enabled. Waiting for documents…")
    await _broadcast({"type": "autoscan_status", "enabled": True, "scanning": False})

    while _autoscan_enabled:
        # Pause while a manual scan is active
        if _active_task and not _active_task.done():
            await asyncio.sleep(1)
            continue

        settings = _autoscan_settings

        # Load + patch base config
        try:
            with open(SETTINGS_FILE) as fh:
                base_config = json.load(fh)
        except Exception as exc:
            log("error", f"Failed to load settings.json: {exc}")
            await asyncio.sleep(5)
            continue

        conf_preset = base_config["Preset"][0]["0"][0]
        if settings.dpi:
            conf_preset["Resolution"]["int"] = settings.dpi
        if settings.duplex:
            conf_preset["DuplexType"]["int"] = 1
        if settings.blank_page_skip:
            conf_preset["BlankPageSkip"]["int"] = 1

        # Prepare an unregistered batch slot
        batch_id = str(uuid.uuid4())
        batch_dir = BATCHES_DIR / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        tmp_config = batch_dir / "settings.sf2"
        conf_preset["UserDefinePath"]["string"] = str(batch_dir)

        pages_scanned = 0
        batch_registered = False
        batch_ts = ""
        no_doc_deadline: Optional[float] = None

        while _autoscan_enabled:
            if _active_task and not _active_task.done():
                await asyncio.sleep(1)
                continue

            conf_preset["FileNamePrefix"]["string"] = f"scan{pages_scanned + 1:03}"
            with open(tmp_config, "w") as fh:
                json.dump(base_config, fh)

            stdout = await loop.run_in_executor(
                _executor, lambda: _epsonscan2(tmp_config)
            )

            is_success = stdout == b"" or (stdout and not stdout.startswith(b"ERROR "))
            is_no_doc = stdout == ES2_STATUS.NO_DOCUMENT.value
            is_fatal = stdout in (
                ES2_STATUS.DEVICE_NOT_FOUND.value,
                ES2_STATUS.CONNECTION_ERROR.value,
                ES2_STATUS.UNEXPECTED_ERROR.value,
            )

            if is_success:
                no_doc_deadline = None
                if not batch_registered:
                    batch_registered = True
                    now = datetime.now()
                    batch_ts = now.strftime("%Y%m%d_%H%M%S")
                    index = _load_index()
                    index["batches"].insert(0, {
                        "id": batch_id,
                        "name": f"batch_{batch_ts}",
                        "created_at": now.isoformat(),
                        "status": "scanning",
                        "pages": 0,
                        "format": settings.format,
                        "output_dir": settings.output_dir,
                        "files": [],
                    })
                    _save_index(index)
                    await _broadcast({"type": "batch_created", "batch_id": batch_id})
                    await _broadcast({"type": "autoscan_status", "enabled": True, "scanning": True})
                    log("info", f"Auto-scan: new batch {batch_id[:8]}")
                pages_scanned += 1
                if stdout:
                    log("info", f"epsonscan2: {stdout.decode(errors='replace').strip()}")
                log("info", f"Auto-scan: scanned page {pages_scanned}")

            elif is_no_doc:
                if pages_scanned == 0:
                    # Still waiting for first page — silently poll
                    await asyncio.sleep(1)
                    continue
                else:
                    if no_doc_deadline is None:
                        no_doc_deadline = time.monotonic() + settings.timeout
                        log("info", f"ADF empty. Finalizing batch in {int(settings.timeout)}s…")
                    if time.monotonic() >= no_doc_deadline:
                        break  # → finalize batch
                    await asyncio.sleep(1)

            elif is_fatal:
                log("error", f"Scanner error: {stdout.decode(errors='replace').strip()}")
                if not batch_registered:
                    shutil.rmtree(batch_dir, ignore_errors=True)
                await asyncio.sleep(5)
                break  # restart outer loop

            else:
                log("critical", f"Unknown epsonscan2 output: {stdout!r}")
                await asyncio.sleep(3)
                break

        # ── Finalize batch ────────────────────────────────────────────────────
        if batch_registered and pages_scanned > 0:
            log("info", "Processing batch…")
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda: Scanner._postprocess(settings, batch_dir, pages_scanned, log, batch_ts),
                )
            except Exception as exc:
                result = {"success": False, "pages": pages_scanned, "files": []}
                log("error", f"Post-process failed: {exc}")

            final_files = result.get("files", [])
            if result["success"] and settings.output_dir:
                dest = pathlib.Path(settings.output_dir)
                try:
                    dest.mkdir(parents=True, exist_ok=True)
                    for fname in final_files:
                        shutil.copy2(batch_dir / fname, dest / fname)
                    log("info", f"Files saved to {dest}")
                    shutil.rmtree(batch_dir, ignore_errors=True)
                    final_files = [str(dest / f) for f in final_files]
                except Exception as exc:
                    log("warning", f"Could not copy to output directory: {exc}")

            index = _load_index()
            for batch in index["batches"]:
                if batch["id"] == batch_id:
                    batch["status"] = "done" if result["success"] else "failed"
                    batch["pages"] = result.get("pages", 0)
                    batch["files"] = final_files
                    break
            _save_index(index)

            await _broadcast({
                "type": "scan_complete",
                "batch_id": batch_id,
                "success": result["success"],
                "pages": result.get("pages", 0),
                "status": "done" if result["success"] else "failed",
                "files": final_files,
            })
            if settings.webhook_url:
                await loop.run_in_executor(
                    None,
                    lambda: _fire_webhook(settings.webhook_url, {
                        "event": "scan_complete",
                        "batch_id": batch_id,
                        "success": result["success"],
                        "pages": result.get("pages", 0),
                        "files": final_files,
                    }),
                )
            await _broadcast({"type": "autoscan_status", "enabled": True, "scanning": False})
            log("info", "Auto-scan ready for next document.")
        elif not batch_registered:
            shutil.rmtree(batch_dir, ignore_errors=True)

    log("info", "Auto-scan disabled.")
    await _broadcast({"type": "autoscan_status", "enabled": False, "scanning": False})
    _autoscan_task = None


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    """High-level status suitable for external polling."""
    scanning = _active_task is not None and not _active_task.done()
    autoscan_active = _autoscan_enabled and _autoscan_task is not None and not _autoscan_task.done()
    if scanning:
        state = "scanning"
    elif autoscan_active:
        state = "autoscan_waiting"
    else:
        state = "idle"
    return {
        "state": state,
        "scanning": scanning,
        "autoscan_enabled": autoscan_active,
    }


@app.get("/api/config")
def get_config():
    """Return the current defaults from config.json for the UI to pre-fill."""
    return _load_config()


@app.on_event("startup")
async def _on_startup():
    """Auto-start autoscan if configured."""
    global _autoscan_enabled, _autoscan_task, _autoscan_settings
    config = _load_config()
    if config.get("autostart_autoscan"):
        _autoscan_settings = ScanSettings(
            timeout=float(config.get("timeout", 10)),
            format=config.get("format", "pdf"),
            dpi=int(config["dpi"]) if config.get("dpi") else None,
            duplex=bool(config.get("duplex", False)),
            blank_page_skip=bool(config.get("blank_page_skip", False)),
            output_dir=str(config.get("output_dir", "")),
            webhook_url=str(config.get("webhook_url", "")),
        )
        _autoscan_enabled = True
        _autoscan_task = asyncio.create_task(_autoscan_loop())


@app.get("/api/batches")
def list_batches():
    return _load_index()["batches"]


@app.get("/api/scan/status")
def scan_status():
    scanning = _active_task is not None and not _active_task.done()
    autoscan = _autoscan_enabled and _autoscan_task is not None and not _autoscan_task.done()
    return {"scanning": scanning, "autoscan": autoscan}


@app.post("/api/scan/start")
async def start_scan(req: ScanRequest):
    global _active_task
    if _active_task and not _active_task.done():
        raise HTTPException(status_code=409, detail="A scan is already in progress.")
    if _autoscan_enabled and _autoscan_task and not _autoscan_task.done():
        raise HTTPException(status_code=409, detail="Auto-scan is active. Disable it first.")
    if req.format not in ("pdf", "png", "jpg"):
        raise HTTPException(status_code=400, detail="format must be pdf, png, or jpg.")

    batch_id = str(uuid.uuid4())
    settings = ScanSettings(
        timeout=req.timeout,
        format=req.format,
        dpi=req.dpi,
        duplex=req.duplex,
        blank_page_skip=req.blank_page_skip,
        output_dir=req.output_dir.strip(),
        webhook_url=req.webhook_url.strip(),
    )
    _active_task = asyncio.create_task(_scan_task(batch_id, settings))
    return {"batch_id": batch_id, "status": "started"}


@app.post("/api/scan/stop")
async def stop_scan():
    _scanner.stop()
    return {"status": "stop requested"}


@app.get("/api/autoscan/status")
def get_autoscan_status():
    active = _autoscan_enabled and _autoscan_task is not None and not _autoscan_task.done()
    return {"enabled": active}


@app.post("/api/autoscan/enable")
async def enable_autoscan(req: ScanRequest):
    global _autoscan_enabled, _autoscan_task, _autoscan_settings
    if _autoscan_task and not _autoscan_task.done():
        raise HTTPException(status_code=409, detail="Auto-scan is already active.")
    if _active_task and not _active_task.done():
        raise HTTPException(status_code=409, detail="A manual scan is in progress.")
    if req.format not in ("pdf", "png", "jpg"):
        raise HTTPException(status_code=400, detail="format must be pdf, png, or jpg.")
    _autoscan_settings = ScanSettings(
        timeout=req.timeout,
        format=req.format,
        dpi=req.dpi,
        duplex=req.duplex,
        blank_page_skip=req.blank_page_skip,
        output_dir=req.output_dir.strip(),
        webhook_url=req.webhook_url.strip(),
    )
    _autoscan_enabled = True
    _autoscan_task = asyncio.create_task(_autoscan_loop())
    return {"status": "enabled"}


@app.post("/api/autoscan/disable")
async def disable_autoscan():
    global _autoscan_enabled
    _autoscan_enabled = False
    return {"status": "disabled"}


@app.put("/api/batches/{batch_id}")
async def rename_batch(batch_id: str, req: RenameRequest):
    if not UUID_RE.match(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="Name too long (max 255 characters).")
    if not SAFE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Name contains invalid characters. Use letters, numbers, spaces, hyphens, underscores, or periods.",
        )

    index = _load_index()
    batch = next((b for b in index["batches"] if b["id"] == batch_id), None)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")

    batch["name"] = name

    # Rename the output file on disk (keep its extension).
    new_files = list(batch.get("files", []))
    if new_files and batch.get("status") == "done":
        old_stored = new_files[0]
        old_rel = pathlib.Path(old_stored)
        is_local = not old_rel.is_absolute()

        if is_local:
            # Relative filename → file lives inside the batch dir
            old_abs = (BATCHES_DIR / batch_id / old_stored).resolve()
            ext = old_rel.suffix
        else:
            old_abs = old_rel.resolve()
            ext = old_abs.suffix

        new_abs = old_abs.parent / (name + ext)

        if old_abs.exists() and new_abs != old_abs:
            if new_abs.exists():
                raise HTTPException(status_code=409, detail="A file with that name already exists.")
            try:
                old_abs.rename(new_abs)
                # Keep the same relative/absolute format in the index
                new_files[0] = (name + ext) if is_local else str(new_abs)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Could not rename file: {exc}")

    batch["files"] = new_files
    _save_index(index)
    await _broadcast({"type": "batch_renamed", "batch_id": batch_id, "name": name, "files": new_files})
    return {"ok": True}


class RenameFileRequest(BaseModel):
    filename: str


@app.post("/api/batches/{batch_id}/rename-file")
async def rename_batch_file(batch_id: str, req: RenameFileRequest):
    """Rename the output file on disk and update the index."""
    if not UUID_RE.match(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")

    new_name = req.filename.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty.")
    # Reject any path separators to prevent directory traversal
    if "/" in new_name or "\\" in new_name or new_name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    index = _load_index()
    batch = next((b for b in index["batches"] if b["id"] == batch_id), None)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    if batch["status"] != "done" or not batch.get("files"):
        raise HTTPException(status_code=409, detail="Batch has no completed files to rename.")

    old_path_str = batch["files"][0]
    old_path = pathlib.Path(old_path_str)
    new_path = old_path.parent / new_name

    if not old_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found on disk.")
    if new_path.exists() and new_path != old_path:
        raise HTTPException(status_code=409, detail="A file with that name already exists.")

    try:
        old_path.rename(new_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not rename file: {exc}")

    # Update every entry in files[] that matches the old path
    batch["files"] = [
        str(new_path) if f == old_path_str else f
        for f in batch["files"]
    ]
    _save_index(index)

    await _broadcast({
        "type": "batch_file_renamed",
        "batch_id": batch_id,
        "files": batch["files"],
    })
    return {"ok": True, "files": batch["files"]}


@app.delete("/api/batches/{batch_id}")
async def delete_batch(batch_id: str):
    if not UUID_RE.match(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")

    index = _load_index()
    batch = next((b for b in index["batches"] if b["id"] == batch_id), None)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")

    # Delete the actual output files from wherever they live.
    for file_path_str in batch.get("files", []):
        old_rel = pathlib.Path(file_path_str)
        file_path = old_rel if old_rel.is_absolute() else (BATCHES_DIR / batch_id / file_path_str)
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass

    index["batches"] = [b for b in index["batches"] if b["id"] != batch_id]
    _save_index(index)

    # Remove the local batch working directory if it still exists.
    batch_dir = BATCHES_DIR / batch_id
    if batch_dir.exists():
        shutil.rmtree(batch_dir)

    await _broadcast({"type": "batch_deleted", "batch_id": batch_id})
    return {"ok": True}


@app.get("/api/batches/{batch_id}/files/{filename}")
def get_batch_file(batch_id: str, filename: str):
    if not UUID_RE.match(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")

    batches_root = BATCHES_DIR.resolve()
    batch_dir = (BATCHES_DIR / batch_id).resolve()

    # Ensure batch_dir is inside BATCHES_DIR (prevent traversal via batch_id)
    if not str(batch_dir).startswith(str(batches_root) + "/"):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")

    file_path = (batch_dir / filename).resolve()

    # Ensure file_path is inside batch_dir (prevent traversal via filename)
    if not str(file_path).startswith(str(batch_dir) + "/"):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(str(file_path))


@app.get("/api/batches/{batch_id}/preview/{file_index}")
def get_batch_preview(
    batch_id: str,
    file_index: int,
    download: bool = Query(default=False),
):
    """Serve a batch output file by its index in files[]. Works for both local
    and external (absolute) paths, since the path is taken from the trusted index.
    Pass ?download=true to get Content-Disposition: attachment for browser downloads."""
    if not UUID_RE.match(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch ID.")

    index = _load_index()
    batch = next((b for b in index["batches"] if b["id"] == batch_id), None)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")

    files = batch.get("files", [])
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="File index out of range.")

    stored = files[file_index]
    stored_path = pathlib.Path(stored)

    # Resolve local (relative) paths to the batch directory
    if stored_path.is_absolute():
        file_path = stored_path.resolve()
    else:
        file_path = (BATCHES_DIR / batch_id / stored).resolve()

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk.")

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{file_path.name}"'

    return FileResponse(str(file_path), headers=headers)


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)

    # Send current scan status immediately so the client can sync on connect
    scanning = _active_task is not None and not _active_task.done()
    await websocket.send_text(json.dumps({"type": "status", "scanning": scanning}))

    try:
        while True:
            await websocket.receive_text()   # keeps the connection alive
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)


# ─── Serve built frontend (production) ───────────────────────────────────────
_frontend_dist = BASE_DIR / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")
