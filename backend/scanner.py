import glob
import json
import pathlib
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, List, Optional


class ES2_STATUS(Enum):
    DEVICE_NOT_FOUND = b"ERROR : Device is not found...\n"
    CONNECTION_ERROR = b"ERROR : Unable to send data. Check the connection to the scanner and try again.\n"
    UNEXPECTED_ERROR = b"ERROR : An unexpected error occurred. Epson Scan 2 will close."
    NO_DOCUMENT = b"ERROR : Load the originals in the ADF.\n"
    ALL_OKAY = b""


@dataclass
class ScanSettings:
    timeout: float = 10.0
    format: str = "pdf"          # "pdf" | "png" | "jpg"
    dpi: Optional[int] = None
    duplex: bool = False
    blank_page_skip: bool = False
    output_dir: str = ""
    webhook_url: str = ""


class Scanner:
    def __init__(self, base_config_path: str) -> None:
        self.base_config_path = base_config_path
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(
        self,
        settings: ScanSettings,
        batch_dir: pathlib.Path,
        log: Callable[[str, str], None],
        timestamp: str = "",
    ) -> dict:
        """
        Perform the scan loop and post-process output.

        log(level, message) is called from this thread for each status update.
        Returns a dict: {"success": bool, "pages": int, "files": list[str]}.
        """
        self._stop_event.clear()

        # ── Load base config ──────────────────────────────────────────────────
        try:
            with open(self.base_config_path) as fh:
                base_config = json.load(fh)
        except FileNotFoundError:
            log("error", f"Settings file not found: {self.base_config_path}")
            return {"success": False, "pages": 0, "files": []}
        except json.JSONDecodeError as exc:
            log("error", f"Settings file is not valid JSON ({self.base_config_path}): {exc}")
            return {"success": False, "pages": 0, "files": []}

        conf_preset = base_config["Preset"][0]["0"][0]
        conf_preset["UserDefinePath"]["string"] = str(batch_dir)

        if settings.dpi is not None:
            conf_preset["Resolution"]["int"] = settings.dpi
            log("info", f"DPI set to {settings.dpi}")
        if settings.duplex:
            conf_preset["DuplexType"]["int"] = 1
            log("info", "Duplex scanning enabled")
        if settings.blank_page_skip:
            conf_preset["BlankPageSkip"]["int"] = 1
            log("info", "Blank page skip enabled")

        tmp_config = batch_dir / "settings.sf2"
        pages_scanned = 0
        deadline = time.monotonic() + settings.timeout

        try:
            # ── Scan loop ─────────────────────────────────────────────────────
            while not self._stop_event.is_set():
                conf_preset["FileNamePrefix"]["string"] = f"scan{pages_scanned + 1:03}"
                with open(tmp_config, "w") as fh:
                    json.dump(base_config, fh)

                proc = subprocess.Popen(
                    ["epsonscan2", "-s", str(tmp_config)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                stdout, _ = proc.communicate()

                if stdout == ES2_STATUS.ALL_OKAY.value or (
                    stdout and not stdout.startswith(b"ERROR ")
                ):
                    # epsonscan2 exits with empty stdout on clean success, but some
                    # versions/firmware print informational lines (e.g.
                    # "Save_Image2pngimageCount:").  Anything that isn't blank and
                    # doesn't begin with "ERROR " is treated as a successful scan.
                    if stdout:
                        log("info", f"epsonscan2: {stdout.decode(errors='replace').strip()}")
                    pages_scanned += 1
                    log("info", f"Scanned page {pages_scanned}")
                    deadline = time.monotonic() + settings.timeout

                elif stdout == ES2_STATUS.NO_DOCUMENT.value:
                    if pages_scanned > 0:
                        log("info", "No more pages in ADF. Document complete.")
                        break
                    if time.monotonic() >= deadline:
                        log("warning", f"Timeout after {settings.timeout}s waiting for document.")
                        break
                    log("info", "Waiting for document in ADF...")
                    self._stop_event.wait(timeout=1.0)

                elif stdout == ES2_STATUS.DEVICE_NOT_FOUND.value:
                    log("error", "Scanner device not found!")
                    return {"success": False, "pages": pages_scanned, "files": []}

                elif stdout == ES2_STATUS.CONNECTION_ERROR.value:
                    log("error", "Connection error to scanner!")
                    return {"success": False, "pages": pages_scanned, "files": []}

                elif stdout == ES2_STATUS.UNEXPECTED_ERROR.value:
                    log("error", "epsonscan2 unexpectedly closed.")
                    return {"success": False, "pages": pages_scanned, "files": []}

                else:
                    log("critical", f"Unknown epsonscan2 status: {stdout!r}")
                    return {"success": False, "pages": pages_scanned, "files": []}

            if self._stop_event.is_set():
                log("warning", "Scan stopped by user.")

            if pages_scanned == 0:
                log("warning", "No pages were scanned.")
                return {"success": False, "pages": 0, "files": []}

            # ── Post-process ──────────────────────────────────────────────────
            return self._postprocess(settings, batch_dir, pages_scanned, log, timestamp)

        finally:
            if tmp_config.exists():
                tmp_config.unlink()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _postprocess(
        settings: ScanSettings,
        batch_dir: pathlib.Path,
        pages_scanned: int,
        log: Callable,
        timestamp: str = "",
    ) -> dict:
        png_files: List[str] = sorted(glob.glob(str(batch_dir / "scan*.png")))
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")

        if settings.format == "pdf":
            if not shutil.which("convert"):
                log("error", "'convert' (ImageMagick) not found in PATH.")
                return {"success": False, "pages": pages_scanned, "files": []}

            pdf_name = f"batch_{ts}.pdf"
            pdf_path = batch_dir / pdf_name
            result = subprocess.run(
                ["convert", "-adjoin"] + png_files + [str(pdf_path)],
                capture_output=True,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode()
                if "not authorized" in stderr.lower() or "policy" in stderr.lower():
                    log(
                        "error",
                        "PDF conversion blocked by ImageMagick policy. "
                        "Edit /etc/ImageMagick-6/policy.xml to allow PDF writing.",
                    )
                else:
                    log("error", f"PDF conversion failed: {stderr.strip()}")
                return {"success": False, "pages": pages_scanned, "files": []}

            for f in png_files:
                pathlib.Path(f).unlink()
            log("info", f"PDF created: {pages_scanned} page(s).")
            return {"success": True, "pages": pages_scanned, "files": [pdf_name], "format": "pdf"}

        elif settings.format == "jpg":
            if not shutil.which("convert"):
                log("error", "'convert' (ImageMagick) not found in PATH.")
                return {"success": False, "pages": pages_scanned, "files": []}

            output_files = []
            for i, png in enumerate(png_files):
                jpg_name = f"scan{i+1:03}_{ts}.jpg"
                jpg = batch_dir / jpg_name
                result = subprocess.run(["convert", png, str(jpg)], capture_output=True)
                if result.returncode == 0:
                    pathlib.Path(png).unlink()
                    output_files.append(jpg_name)
                else:
                    log("error", f"JPG conversion failed for {png}: {result.stderr.decode().strip()}")
            log("info", f"Converted {len(output_files)} page(s) to JPG.")
            return {"success": True, "pages": pages_scanned, "files": output_files, "format": "jpg"}

        else:  # png
            output_files = []
            for i, f in enumerate(png_files):
                png_name = f"scan{i+1:03}_{ts}.png"
                pathlib.Path(f).rename(batch_dir / png_name)
                output_files.append(png_name)
            log("info", f"Saved {pages_scanned} page(s) as PNG.")
            return {"success": True, "pages": pages_scanned, "files": output_files, "format": "png"}
