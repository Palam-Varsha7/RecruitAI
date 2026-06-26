#!/usr/bin/env python3
"""Generate a simple PDF deck from docs/approach_deck.md using stdlib only."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "approach_deck.md"
OUT = ROOT / "docs" / "approach_deck.pdf"
PAGE_W = 792
PAGE_H = 612
MARGIN = 56


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def split_slides(markdown: str) -> list[tuple[str, list[str]]]:
    slides: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if current_title:
                slides.append((current_title, current_lines))
            current_title = line[3:].strip()
            current_lines = []
        elif line.startswith("# "):
            if not current_title:
                current_title = line[2:].strip()
        else:
            current_lines.append(line)
    if current_title:
        slides.append((current_title, current_lines))
    return slides


def draw_slide(title: str, lines: list[str], slide_no: int, total: int) -> str:
    stream: list[str] = []
    stream.append("0.08 0.10 0.13 rg 0 0 792 612 re f")
    stream.append("0.00 0.55 0.50 rg 0 0 792 12 re f")
    stream.append("0.95 0.95 0.92 rg")
    stream.append("BT /F1 30 Tf 56 535 Td")
    stream.append(f"({pdf_escape(title)}) Tj ET")
    y = 485
    in_code = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if not stripped:
            y -= 12
            continue
        bullet = stripped.startswith("- ") or re.match(r"^[0-9]+\\. ", stripped)
        text = re.sub(r"^[0-9]+\\. ", "", stripped[2:] if stripped.startswith("- ") else stripped)
        text = text.replace("`", "")
        wrap_width = 82 if not bullet else 76
        for idx, chunk in enumerate(textwrap.wrap(text, width=wrap_width)):
            if y < 82:
                break
            prefix = "- " if bullet and idx == 0 else "  " if bullet else ""
            size = 15 if not in_code else 13
            stream.append("0.86 0.90 0.88 rg")
            stream.append(f"BT /F2 {size} Tf {MARGIN + (18 if bullet else 0)} {y} Td")
            stream.append(f"({pdf_escape(prefix + chunk)}) Tj ET")
            y -= 24 if not in_code else 20
    stream.append("0.56 0.62 0.60 rg")
    stream.append(f"BT /F2 11 Tf 56 34 Td (RecruitAI | {slide_no}/{total}) Tj ET")
    return "\n".join(stream)


def build_pdf(slides: list[tuple[str, list[str]]]) -> bytes:
    objects: list[bytes] = []

    def add(obj: str | bytes) -> int:
        data = obj.encode("latin-1") if isinstance(obj, str) else obj
        objects.append(data)
        return len(objects)

    pages_id_placeholder = 0
    font1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    font2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for idx, (title, body) in enumerate(slides, start=1):
        content = draw_slide(title, body, idx, len(slides)).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
        content_ids.append(content_id)
        page_id = add(
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"
    pages_id = add(pages_obj)
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    patched: list[bytes] = []
    for i, obj in enumerate(objects, start=1):
        if i in page_ids:
            patched.append(obj.replace(b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode("ascii")))
        else:
            patched.append(obj)

    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets = [0]
    for i, obj in enumerate(patched, start=1):
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(f"{i} 0 obj\n".encode("ascii"))
        chunks.append(obj)
        chunks.append(b"\nendobj\n")
    xref_offset = sum(len(c) for c in chunks)
    chunks.append(f"xref\n0 {len(patched) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        f"trailer << /Size {len(patched) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return b"".join(chunks)


def main() -> None:
    slides = split_slides(SOURCE.read_text(encoding="utf-8"))
    OUT.write_bytes(build_pdf(slides))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
