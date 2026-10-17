from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    PageBreak,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).with_name("High-Concurrency-Booking-Database.pdf")


def inline_markup(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier" color="#176b69">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def wrap_code(source: str, width: int = 95) -> str:
    wrapped_lines: list[str] = []
    for line in source.splitlines():
        if len(line) <= width:
            wrapped_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        wrapped_lines.extend(
            textwrap.wrap(
                line.strip(),
                width=width,
                subsequent_indent=" " * min(indent + 4, 20),
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    return "\n".join(wrapped_lines)


def parse_markdown(path: Path, styles: dict[str, ParagraphStyle]) -> list[object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    story: list[object] = []
    paragraph_lines: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph_lines:
            story.append(Paragraph(inline_markup(" ".join(part.strip() for part in paragraph_lines)), styles["body"]))
            story.append(Spacer(1, 4))
            paragraph_lines.clear()

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush_paragraph()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            story.append(Preformatted(wrap_code("\n".join(code_lines)), styles["SubmissionCode"]))
            story.append(Spacer(1, 8))
            index += 1
            continue

        if line.startswith("|"):
            flush_paragraph()
            rows: list[list[Paragraph]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", cell or " ") for cell in cells):
                    rows.append([Paragraph(inline_markup(cell), styles["table_cell"]) for cell in cells])
                index += 1
            if rows:
                column_count = max(len(row) for row in rows)
                usable_width = A4[0] - 36 * mm
                if column_count == 3:
                    widths = [usable_width * 0.22, usable_width * 0.48, usable_width * 0.30]
                elif column_count == 2:
                    widths = [usable_width * 0.28, usable_width * 0.72]
                else:
                    widths = [usable_width / column_count] * column_count
                padded = [row + [Paragraph("", styles["table_cell"])] * (column_count - len(row)) for row in rows]
                table = Table(padded, colWidths=widths, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183d3b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eff5f3")]),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c8d6d2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                story.extend([table, Spacer(1, 10)])
            continue

        if line.startswith("#"):
            flush_paragraph()
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            style_name = "title" if level == 1 else "heading"
            story.append(Paragraph(inline_markup(title), styles["SubmissionTitle" if style_name == "title" else "SubmissionHeading"]))
            if level == 1 and not story[:-1]:
                story.append(Spacer(1, 8))
            index += 1
            continue

        if line.startswith("- "):
            flush_paragraph()
            story.append(Paragraph("&#8226; " + inline_markup(line[2:]), styles["body"]))
            story.append(Spacer(1, 3))
            index += 1
            continue

        if re.match(r"^\d+\. ", line):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line), styles["body"]))
            story.append(Spacer(1, 3))
            index += 1
            continue

        if not line.strip():
            flush_paragraph()
        else:
            paragraph_lines.append(line)
        index += 1

    flush_paragraph()
    return story


def page_chrome(canvas, document) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.HexColor("#183d3b"))
    canvas.rect(0, height - 13 * mm, width, 13 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(18 * mm, height - 8.5 * mm, "HIGH-CONCURRENCY MOVIE BOOKING | MYSQL DESIGN")
    canvas.setStrokeColor(colors.HexColor("#c8d6d2"))
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(colors.HexColor("#546b68"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, 9 * mm, "MySQL 8.0.16+ | InnoDB | UTC timestamps")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"{document.page}")
    canvas.restoreState()


def main() -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SubmissionTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=23, leading=29, textColor=colors.HexColor("#183d3b"),
        alignment=TA_CENTER, spaceAfter=13,
    ))
    styles.add(ParagraphStyle(
        name="SubmissionHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=colors.HexColor("#176b69"),
        spaceBefore=10, spaceAfter=7, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=13, textColor=colors.HexColor("#203432"),
        spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="table_cell", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=7.4, leading=10, textColor=colors.HexColor("#203432"),
    ))
    styles.add(ParagraphStyle(
        name="SubmissionCode", fontName="Courier", fontSize=6.8, leading=8.2,
        textColor=colors.HexColor("#183d3b"), leftIndent=5, rightIndent=5,
        borderColor=colors.HexColor("#d8e5e1"), borderWidth=0.4,
        borderPadding=5, backColor=colors.HexColor("#f3f7f6"),
    ))

    frame = Frame(18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 38 * mm, id="body")
    document = BaseDocTemplate(
        str(OUTPUT), pagesize=A4, title="High-Concurrency Movie Ticket Booking Database",
        author="Database Design Submission", leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=22 * mm, bottomMargin=18 * mm,
    )
    document.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_chrome)])

    story = parse_markdown(ROOT / "SUBMISSION.md", styles)
    for title, filename in (
        ("Appendix A: MySQL Schema (P1)", "schema.sql"),
        ("Appendix B: Sample Rows (P1)", "seed.sql"),
        ("Appendix C: P2 and Operational SQL", "queries.sql"),
    ):
        story.extend([PageBreak(), Paragraph(title, styles["SubmissionHeading"]), Spacer(1, 4)])
        source = (ROOT / "sql" / filename).read_text(encoding="utf-8")
        story.append(Preformatted(wrap_code(source), styles["SubmissionCode"]))

    document.build(story)
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()