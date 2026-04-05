"""Markdown to PDF report generation + Obsidian vault delivery.

Uses fpdf2 for PDF generation (WeasyPrint requires GTK/Pango native libs
not available on Windows without extra setup).
"""

import os
import re
import shutil
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fpdf import FPDF

load_dotenv()


def get_report_dir() -> Path:
    """Get or create today's report directory."""
    base = Path(os.getenv("REPORTS_DIR", "./reports"))
    report_dir = base / date.today().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def _strip_inline(text: str) -> str:
    """Strip markdown bold markers for plain text rendering."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


class _MarkdownPDF(FPDF):
    """FPDF subclass that renders a minimal markdown subset."""

    def render_markdown(self, markdown_text: str) -> None:
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()

        lines = markdown_text.split("\n")
        in_table = False
        table_rows: list[list[str]] = []
        in_list = False

        for line in lines:
            stripped = line.strip()

            # Flush table when we exit table context
            if in_table and not (stripped.startswith("|") and stripped.endswith("|")):
                self._flush_table(table_rows)
                table_rows = []
                in_table = False

            if stripped.startswith("### "):
                self._render_h3(stripped[4:])
            elif stripped.startswith("## "):
                self._render_h2(stripped[3:])
            elif stripped.startswith("# "):
                self._render_h1(stripped[2:])
            elif stripped.startswith("|") and set(
                stripped.replace("|", "").replace("-", "").replace(" ", "")
            ) == set():
                # Separator row — skip
                continue
            elif stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                in_table = True
                table_rows.append(cells)
            elif stripped.startswith("- "):
                self._render_li(_strip_inline(stripped[2:]))
            elif stripped:
                self._render_p(_strip_inline(stripped))
            else:
                self.ln(2)

        if in_table and table_rows:
            self._flush_table(table_rows)

    def _render_h1(self, text: str) -> None:
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(17, 17, 17)
        self.cell(0, 10, text, ln=True)
        self.set_draw_color(51, 51, 51)
        self.set_line_width(0.5)
        self.line(self.get_x(), self.get_y(), self.get_x() + 170, self.get_y())
        self.ln(4)

    def _render_h2(self, text: str) -> None:
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(34, 34, 34)
        self.cell(0, 8, text, ln=True)
        self.ln(2)

    def _render_h3(self, text: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(51, 51, 51)
        self.cell(0, 7, text, ln=True)

    def _render_p(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.set_text_color(26, 26, 26)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def _render_li(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.set_text_color(26, 26, 26)
        self.cell(6, 6, "-")
        self.multi_cell(0, 6, text)

    def _flush_table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        self.ln(2)
        col_count = len(rows[0])
        col_w = 170 / col_count

        # Header row
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(17, 17, 17)
        for cell in rows[0]:
            self.cell(col_w, 7, cell, border=1, fill=True)
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 9)
        for i, row in enumerate(rows[1:], 1):
            fill = i % 2 == 0
            self.set_fill_color(250, 250, 250) if fill else self.set_fill_color(255, 255, 255)
            for cell in row:
                self.cell(col_w, 6, cell, border=1, fill=fill)
            self.ln()
        self.ln(2)


def generate_pdf(markdown_text: str, output_path: Path) -> None:
    """Convert markdown string to a styled PDF file."""
    pdf = _MarkdownPDF()
    pdf.render_markdown(markdown_text)
    pdf.output(str(output_path))


def copy_to_obsidian(pdf_path: Path) -> None:
    """Copy a PDF report into the Obsidian vault reports folder."""
    vault_path_str = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not vault_path_str:
        print("WARNING: OBSIDIAN_VAULT_PATH not set, skipping copy")
        return
    vault_path = Path(vault_path_str)
    dest_dir = vault_path / "reports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, dest_dir / pdf_path.name)
