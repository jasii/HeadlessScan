#!/usr/bin/env python3

import argparse
import glob
import subprocess
import json
import pathlib
import datetime
import shutil
import time
from enum import Enum
import logging

logging.basicConfig(
    format="%(asctime)s: %(levelname)10s - %(message)s", level=logging.INFO
)
logger = logging.getLogger()


class ES2_STATUS(Enum):
    """Output mapping for epsonscan2."""
    DEVICE_NOT_FOUND = b"ERROR : Device is not found...\n"
    CONNECTION_ERROR = b"ERROR : Unable to send data. Check the connection to the scanner and try again.\n"
    UNEXPECTED_ERROR = b"ERROR : An unexpected error occurred. Epson Scan 2 will close."
    NO_DOCUMENT = b"ERROR : Load the originals in the ADF.\n"
    ALL_OKAY = b""


def check_dependencies():
    """Verify required external tools are available."""
    missing = [cmd for cmd in ("epsonscan2", "convert") if not shutil.which(cmd)]
    if missing:
        raise SystemExit(f"Missing required tool(s): {', '.join(missing)}")


def read_base_config(baseconfig_file):
    with open(baseconfig_file) as cf:
        base_config = json.load(cf)
    return base_config


def write_scan_config(config, out_file):
    with open(out_file, "w") as cf:
        json.dump(config, cf)
    logger.debug(f"Wrote scan config to {out_file}.")


def epsonscan2(settings_file):
    """Run epsonscan2"""
    logger.info("Scanning...")
    proc = subprocess.Popen(["epsonscan2", "-s", str(settings_file)], stdout=subprocess.PIPE)
    stdout, _ = proc.communicate()
    logger.debug(f'epsonscan2 returned: "{str(stdout)}"')
    return stdout


def convert_scans_to_pdf(tmp_path, out_file):
    scan_files = sorted(glob.glob(str(tmp_path / "scan*.png")))
    if not scan_files:
        logger.warning("No scanned pages found, skipping PDF conversion.")
        return False
    subprocess.run(["convert", "-adjoin"] + scan_files + [str(out_file)], check=True)
    return True


def main():
    parser = argparse.ArgumentParser(description="Scan multipage documents.")
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for a page before ending the document.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=None,
        help="Output PDF path. Defaults to scan_YYYYMMDD_HHMMSS.pdf in the current directory.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="Scan resolution in DPI (overrides settings file).",
    )
    parser.add_argument(
        "--duplex",
        action="store_true",
        default=None,
        help="Enable duplex (double-sided) scanning.",
    )
    parser.add_argument(
        "--blank-page-skip",
        action="store_true",
        default=None,
        help="Skip blank pages.",
    )
    parser.add_argument("settingsfile", help="Base settings file to use for scanning.")
    args = parser.parse_args()

    check_dependencies()

    now = datetime.datetime.now()
    out_file = args.output if args.output else pathlib.Path(f"scan_{now.strftime('%Y%m%d_%H%M%S')}.pdf")
    tmp_path = pathlib.Path(f"./scan_{now.strftime('%Y%m%d_%H%M%S')}/")
    tmp_path.mkdir()
    tmp_config = tmp_path / "settings.sf2"

    base_config = read_base_config(pathlib.Path(args.settingsfile))
    conf_preset = base_config["Preset"][0]["0"][0]
    conf_preset["UserDefinePath"]["string"] = str(tmp_path)

    if args.dpi is not None:
        conf_preset["Resolution"]["int"] = args.dpi
        logger.info(f"DPI set to {args.dpi}.")
    if args.duplex is not None:
        conf_preset["DuplexType"]["int"] = 1 if args.duplex else 0
        logger.info(f"Duplex {'enabled' if args.duplex else 'disabled'}.")
    if args.blank_page_skip is not None:
        conf_preset["BlankPageSkip"]["int"] = 1 if args.blank_page_skip else 0
        logger.info(f"Blank page skip {'enabled' if args.blank_page_skip else 'disabled'}.")

    pages_scanned = 0
    fatal_error = False
    deadline = time.monotonic() + args.timeout

    try:
        while True:
            conf_preset["FileNamePrefix"]["string"] = f"scan{pages_scanned + 1:03}"
            write_scan_config(base_config, out_file=tmp_config)
            logger.debug(f'Scanning {conf_preset["FileNamePrefix"]["string"]}.png...')
            stdout = epsonscan2(tmp_config)

            if stdout == ES2_STATUS.ALL_OKAY.value:
                pages_scanned += 1
                logger.info(f"Successfully scanned page {pages_scanned}.")
                deadline = time.monotonic() + args.timeout

            elif stdout == ES2_STATUS.NO_DOCUMENT.value:
                if pages_scanned > 0:
                    logger.info("No more pages in ADF. Document complete.")
                    break
                if time.monotonic() >= deadline:
                    logger.warning(f"Timeout after {args.timeout}s waiting for document. Exiting.")
                    break
                logger.info("Waiting for document in ADF...")
                time.sleep(1)

            elif stdout == ES2_STATUS.DEVICE_NOT_FOUND.value:
                logger.error("Scanner device not found!")
                fatal_error = True
                break

            elif stdout == ES2_STATUS.CONNECTION_ERROR.value:
                logger.error("Connection error to scanner!")
                fatal_error = True
                break

            elif stdout == ES2_STATUS.UNEXPECTED_ERROR.value:
                logger.error("epsonscan2 unexpectedly closed.")
                fatal_error = True
                break

            else:
                logger.critical(f'Unknown epsonscan2 status: "{str(stdout)}"')
                fatal_error = True
                break

        if not fatal_error and pages_scanned > 0:
            if convert_scans_to_pdf(tmp_path, out_file):
                logger.info(f"Scan complete: {pages_scanned} page(s) saved to '{out_file}'.")
        elif pages_scanned == 0:
            logger.warning("No pages were scanned. No PDF created.")

    finally:
        shutil.rmtree(tmp_path)


if __name__ == "__main__":
    main()