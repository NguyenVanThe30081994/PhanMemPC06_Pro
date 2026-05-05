# -*- coding: utf-8 -*-
"""
Recalculate uploaded Excel workbooks using LibreOffice Calc when available.

This is the only practical way to get broad Excel-formula compatibility on
the server side without depending on a local desktop Excel process.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url


class ExcelRecalcService:
    @staticmethod
    def _resolve_soffice_binary():
        configured = (os.getenv("LIBREOFFICE_BIN") or "").strip()
        if configured:
            return configured
        return shutil.which("soffice")

    @classmethod
    def is_available(cls):
        return bool(cls._resolve_soffice_binary())

    @staticmethod
    def _file_url(path):
        return urljoin("file:", pathname2url(str(path)))

    @classmethod
    def recalc_xlsx_bytes(cls, workbook_bytes):
        soffice = cls._resolve_soffice_binary()
        if not soffice:
            raise RuntimeError("LibreOffice/soffice is not installed on this server")

        with tempfile.TemporaryDirectory(prefix="pc06-recalc-") as temp_dir:
            temp_path = Path(temp_dir)
            input_dir = temp_path / "input"
            output_dir = temp_path / "output"
            profile_dir = temp_path / "lo-profile"
            input_dir.mkdir()
            output_dir.mkdir()
            profile_dir.mkdir()

            input_file = input_dir / "report.xlsx"
            input_file.write_bytes(workbook_bytes)

            command = [
                soffice,
                "--headless",
                "--nologo",
                "--norestore",
                f"-env:UserInstallation={cls._file_url(profile_dir)}",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(output_dir),
                str(input_file),
            ]

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                check=False,
            )

            output_file = output_dir / "report.xlsx"
            if result.returncode != 0 or not output_file.exists():
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(detail or "LibreOffice failed to recalculate workbook")

            return output_file.read_bytes()
