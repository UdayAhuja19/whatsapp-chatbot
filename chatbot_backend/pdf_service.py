"""
pdf_service.py — Professional PDF generation using ReportLab Platypus.

Converts Claude's markdown-formatted text into polished, multi-page PDF
documents with styled headings, bullet points, code blocks, and
a branded header/footer on every page.
"""

import os
import re
import tempfile
from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — no GUI needed
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, PageBreak, KeepTogether, Image,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ═══════════════════════════════════════════════════════════════════
# COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════════
PRIMARY      = HexColor("#1E3A8A")   # Deep blue — headings, header bar
ACCENT       = HexColor("#3B82F6")   # Bright blue — sub-headings, links
DARK_TEXT     = HexColor("#1F2937")   # Near-black — body text
LIGHT_TEXT    = HexColor("#6B7280")   # Grey — captions, footer
CODE_BG      = HexColor("#F3F4F6")   # Light grey — code block background
CODE_BORDER  = HexColor("#D1D5DB")   # Border for code blocks
BULLET_COLOR = HexColor("#3B82F6")   # Blue bullet marker
DIVIDER      = HexColor("#E5E7EB")   # Thin dividers between sections
WHITE        = HexColor("#FFFFFF")

# ═══════════════════════════════════════════════════════════════════
# PAGE DIMENSIONS
# ═══════════════════════════════════════════════════════════════════
PAGE_W, PAGE_H = A4                  # 210 x 297 mm
MARGIN_LEFT   = 20 * mm
MARGIN_RIGHT  = 20 * mm
MARGIN_TOP    = 30 * mm              # Room for graphical header bar
MARGIN_BOTTOM = 22 * mm              # Room for footer


# ═══════════════════════════════════════════════════════════════════
# CUSTOM STYLES
# ═══════════════════════════════════════════════════════════════════
def _build_styles():
    """Return a dictionary of ParagraphStyles used throughout the PDF."""
    base = getSampleStyleSheet()

    styles = {}

    styles["title"] = ParagraphStyle(
        "DocTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=PRIMARY,
        alignment=TA_LEFT,
        spaceAfter=4 * mm,
    )

    styles["subtitle"] = ParagraphStyle(
        "DocSubtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        textColor=LIGHT_TEXT,
        alignment=TA_LEFT,
        spaceAfter=6 * mm,
    )

    styles["h1"] = ParagraphStyle(
        "Heading1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=PRIMARY,
        spaceBefore=8 * mm,
        spaceAfter=3 * mm,
        borderPadding=(0, 0, 2, 0),
    )

    styles["h2"] = ParagraphStyle(
        "Heading2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=ACCENT,
        spaceBefore=6 * mm,
        spaceAfter=2 * mm,
    )

    styles["h3"] = ParagraphStyle(
        "Heading3",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=DARK_TEXT,
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )

    styles["body"] = ParagraphStyle(
        "BodyText",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=DARK_TEXT,
        alignment=TA_JUSTIFY,
        spaceAfter=2.5 * mm,
    )

    styles["bullet"] = ParagraphStyle(
        "BulletItem",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=DARK_TEXT,
        leftIndent=12 * mm,
        firstLineIndent=0,
        spaceAfter=1.5 * mm,
        bulletIndent=5 * mm,
        bulletFontSize=10,
        bulletColor=BULLET_COLOR,
    )

    styles["numbered"] = ParagraphStyle(
        "NumberedItem",
        parent=styles["bullet"],
        bulletColor=PRIMARY,
    )

    styles["code"] = ParagraphStyle(
        "CodeBlock",
        parent=base["Code"],
        fontName="Courier",
        fontSize=9,
        leading=12,
        textColor=DARK_TEXT,
        backColor=CODE_BG,
        borderWidth=0.5,
        borderColor=CODE_BORDER,
        borderPadding=8,
        leftIndent=6 * mm,
        rightIndent=6 * mm,
        spaceAfter=3 * mm,
        spaceBefore=2 * mm,
    )

    return styles


# ═══════════════════════════════════════════════════════════════════
# LATEX MATH RENDERING (LaTeX → PNG image → ReportLab Image flowable)
# ═══════════════════════════════════════════════════════════════════

# Usable width for math images (page width minus both margins)
_MATH_MAX_WIDTH = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT

# Pre-create a reusable figure and axis to avoid the overhead of
# creating a new matplotlib figure for every single equation.
# This cuts render time from ~2s/equation to ~0.3s/equation.
_reusable_fig, _reusable_ax = plt.subplots(figsize=(6, 0.8))
_reusable_ax.axis("off")


def _render_latex(latex_str: str, fontsize: int = 12, display: bool = True) -> Optional[Image]:
    """
    Render a LaTeX math string to a PNG in memory using matplotlib,
    then return a ReportLab Image flowable that fits within page margins.
    Reuses a single figure object for speed.
    """
    try:
        ax = _reusable_ax
        fig = _reusable_fig

        # Clear previous content
        ax.clear()
        ax.axis("off")

        # Resize figure based on display mode
        fig.set_size_inches(6, 0.8 if display else 0.5)

        # Clean up the expression: ensure it's wrapped in exactly one pair of $
        expr = latex_str.strip()
        while expr.startswith("$"):
            expr = expr[1:]
        while expr.endswith("$"):
            expr = expr[:-1]
        expr = expr.strip()
        expr = f"${expr}$"

        ax.text(
            0.0, 0.5, expr,  # Start at x=0 for left alignment
            fontsize=fontsize,
            ha="left", va="center", # Align left instead of center
            transform=ax.transAxes,
        )

        buf = BytesIO()
        fig.savefig(
            buf, format="png", dpi=150,
            bbox_inches="tight", transparent=False,
            facecolor="white", pad_inches=0.02, # Reduced padding drastically
        )
        buf.seek(0)

        # Create the ReportLab Image and scale to fit page width
        img = Image(buf)
        if img.drawWidth > _MATH_MAX_WIDTH:
            scale = _MATH_MAX_WIDTH / img.drawWidth
            img.drawWidth *= scale
            img.drawHeight *= scale

        return img

    except Exception as e:
        print(f"[pdf_service] LaTeX render failed for: {latex_str[:60]}... — {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# MARKDOWN PARSER (Claude output → Flowable list)
# ═══════════════════════════════════════════════════════════════════

def _safe(text: str) -> str:
    """Escape XML special characters for ReportLab Paragraphs, and replace
    unsupported Unicode with readable ASCII equivalents."""
    # Map common Unicode symbols to ASCII-safe replacements
    UNICODE_REPLACEMENTS = {
        "\u2713": "[/]",   # ✓ checkmark
        "\u2714": "[/]",   # ✔ heavy checkmark
        "\u2715": "[x]",   # ✕ multiplication x
        "\u2716": "[x]",   # ✖ heavy multiplication x
        "\u2717": "[x]",   # ✗ ballot x
        "\u2718": "[x]",   # ✘ heavy ballot x
        "\u2190": "<-",    # ← leftwards arrow
        "\u2192": "->",    # → rightwards arrow
        "\u2191": "^",     # ↑ upwards arrow
        "\u2193": "v",     # ↓ downwards arrow
        "\u2022": "-",     # • bullet (handled separately in bullet style)
        "\u2023": ">",     # ‣ triangular bullet
        "\u2019": "'",     # ' right single quote
        "\u2018": "'",     # ' left single quote
        "\u201C": '"',     # " left double quote
        "\u201D": '"',     # " right double quote
        "\u2014": " -- ",  # — em dash
        "\u2013": " - ",   # – en dash
        "\u2026": "...",   # … ellipsis
        "\u00D7": "x",     # × multiplication sign
        "\u00F7": "/",     # ÷ division sign
        "\u2260": "!=",    # ≠ not equal
        "\u2264": "<=",    # ≤ less than or equal
        "\u2265": ">=",    # ≥ greater than or equal
        "\u221E": "inf",   # ∞ infinity
        "\u2211": "sum",   # ∑ summation
        "\u222B": "integral",  # ∫ integral
        "\u03B1": "alpha",     # α
        "\u03B2": "beta",      # β
        "\u03B3": "gamma",     # γ
        "\u03B4": "delta",     # δ
        "\u03C0": "pi",        # π
        "\u03B8": "theta",     # θ
        "\u25A0": "[#]",   # ■ black square (the boxes you saw)
        "\u25A1": "[ ]",   # □ white square
        "\u25CF": "(*)",   # ● black circle
        "\u25CB": "( )",   # ○ white circle
        "\u2605": "[*]",   # ★ star
        "\u2606": "[*]",   # ☆ white star
    }
    for char, replacement in UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)

    # Remove emojis and any remaining non-Latin-1 characters
    cleaned = []
    for ch in text:
        try:
            ch.encode("latin-1")
            cleaned.append(ch)
        except UnicodeEncodeError:
            cleaned.append("")  # silently drop unrenderable chars
    text = "".join(cleaned)

    # Escape XML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text


def _strip_inline_latex(text: str) -> str:
    """Strip inline $...$ and $$...$$ LaTeX delimiters and render the math content
    as readable text. This runs BEFORE _safe() so we work on raw text."""
    def _latex_to_readable(match):
        expr = match.group(1)
        # Convert common LaTeX commands to readable text
        expr = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", expr)
        expr = re.sub(r"\\dfrac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", expr)
        expr = re.sub(r"\\sqrt\{([^}]*)\}", r"sqrt(\1)", expr)
        expr = re.sub(r"\\int", "integral", expr)
        expr = re.sub(r"\\sum", "sum", expr)
        expr = re.sub(r"\\(sin|cos|tan|log|ln|lim|max|min)", r"\1", expr)
        expr = re.sub(r"\\(alpha|beta|gamma|delta|theta|pi|sigma|omega|lambda|mu|epsilon)", r"\1", expr)
        expr = re.sub(r"\\(left|right|,|;|!|quad|qquad)", " ", expr)
        expr = re.sub(r"\\cdot", "*", expr)
        expr = re.sub(r"\\times", "x", expr)
        expr = re.sub(r"\\pm", "+/-", expr)
        expr = re.sub(r"\\neq", "!=", expr)
        expr = re.sub(r"\\leq", "<=", expr)
        expr = re.sub(r"\\geq", ">=", expr)
        expr = re.sub(r"\\infty", "inf", expr)
        expr = re.sub(r"\\therefore", "therefore", expr)
        expr = re.sub(r"\\[a-zA-Z]+", "", expr)  # Remove any remaining commands
        expr = expr.replace("{", "").replace("}", "")
        expr = re.sub(r"\s+", " ", expr).strip()
        return expr

    # First handle $$...$$ (double dollar), then $...$ (single dollar)
    text = re.sub(r"\$\$(.+?)\$\$", _latex_to_readable, text)
    text = re.sub(r"(?<!\$)\$(?!\$)([^$]+?)\$(?!\$)", _latex_to_readable, text)
    return text


def _inline_format(text: str) -> str:
    """Convert markdown inline formatting to ReportLab XML tags."""
    # First strip inline LaTeX $...$ to readable text
    text = _strip_inline_latex(text)
    text = _safe(text)
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    # Inline code: `text`
    text = re.sub(r"`(.+?)`", r'<font face="Courier" size="9" color="#1F2937">\1</font>', text)
    return text


def _parse_markdown(content: str, styles: dict) -> list:
    """
    Parse Claude's markdown output into a list of ReportLab Flowable objects.
    Handles: headings (#, ##, ###), bullet points, numbered lists,
    code blocks (```), and regular paragraphs.
    """
    flowables = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Empty line → small spacer ──
        if not stripped:
            flowables.append(Spacer(1, 2 * mm))
            i += 1
            continue

        # ── Display math block: $$ ... $$ (can span multiple lines) ──
        if stripped.startswith("$$"):
            math_lines = []
            # Check if $$ opens and closes on the same line: $$ expr $$
            inner = stripped[2:]
            if inner.endswith("$$") and len(inner) > 2:
                math_lines.append(inner[:-2].strip())
            else:
                if inner.strip():
                    math_lines.append(inner.strip())
                i += 1
                while i < len(lines):
                    l = lines[i].strip()
                    if l.endswith("$$"):
                        remainder = l[:-2].strip()
                        if remainder:
                            math_lines.append(remainder)
                        break
                    math_lines.append(l)
                    i += 1
            i += 1  # skip closing line
            latex_expr = " ".join(math_lines)
            img = _render_latex(latex_expr, fontsize=12, display=True)
            if img:
                # Reduced spacing before and after display math
                flowables.append(Spacer(1, 0.5 * mm))
                img.hAlign = 'LEFT' # Ensure ReportLab aligns the image to the left
                flowables.append(img)
                flowables.append(Spacer(1, 0.5 * mm))
            else:
                # Fallback: show as code block
                flowables.append(Paragraph(_safe(latex_expr), styles["code"]))
            continue

        # ── Code block (``` ... ```) ──
        if stripped.startswith("```"):
            # Check if this is a LaTeX math code block: ```latex or ```math
            lang_tag = stripped[3:].strip().lower()
            is_math_block = lang_tag in ("latex", "math", "tex", "equation")

            code_lines = []
            i += 1  # skip the opening ```
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i] if is_math_block else _safe(lines[i]))
                i += 1
            i += 1  # skip the closing ```

            if is_math_block and code_lines:
                # Render each non-empty line as a separate math equation
                for ml in code_lines:
                    ml = ml.strip()
                    if not ml:
                        continue
                    img = _render_latex(ml, fontsize=12, display=True)
                    if img:
                        # Reduced spacing before and after math lines in code blocks
                        flowables.append(Spacer(1, 0.5 * mm))
                        img.hAlign = 'LEFT' # Ensure ReportLab aligns the image to the left
                        flowables.append(img)
                        flowables.append(Spacer(1, 0.5 * mm))
                    else:
                        flowables.append(Paragraph(_safe(ml), styles["code"]))
            else:
                code_text = "<br/>".join(code_lines) if code_lines else "&nbsp;"
                flowables.append(Paragraph(code_text, styles["code"]))
            continue

        # ── Headings ──
        heading_match = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = _inline_format(heading_match.group(2))
            style_key = f"h{level}"
            
            # Force a fresh page if this is the Answer Key heading
            if level == 1 and "answer key" in heading_text.lower():
                flowables.append(PageBreak())
                
            flowables.append(Paragraph(heading_text, styles[style_key]))
            # Add a thin rule under H1 headings for visual separation
            if level == 1:
                flowables.append(HRFlowable(
                    width="100%", thickness=0.5,
                    color=DIVIDER, spaceBefore=0, spaceAfter=3 * mm,
                ))
            i += 1
            continue

        # ── Bullet points: - item or * item or • item ──
        bullet_match = re.match(r"^[\-\*\u2022]\s+(.*)", stripped)
        if bullet_match:
            bullet_content = bullet_match.group(1).strip()
            # Check if bullet content is a $$...$$ math expression
            math_in_bullet = re.match(r"^\$\$(.+?)\$\$$", bullet_content)
            if math_in_bullet:
                # Render bullet marker as text, then math as image
                flowables.append(Paragraph(
                    "\u2022", styles["bullet"],
                ))
                img = _render_latex(math_in_bullet.group(1), fontsize=12, display=True)
                if img:
                    flowables.append(img)
                    flowables.append(Spacer(1, 1.5 * mm))
                else:
                    flowables.append(Paragraph(_safe(bullet_content), styles["code"]))
            else:
                bullet_text = _inline_format(bullet_content)
                flowables.append(Paragraph(
                    bullet_text, styles["bullet"],
                    bulletText="\u2022",  # bullet character
                ))
            i += 1
            continue

        # ── Numbered list: 1. item ──
        num_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if num_match:
            num = num_match.group(1)
            item_content = num_match.group(2).strip()
            # Check if the item content is a $$...$$ math expression
            math_in_num = re.match(r"^\$\$(.+?)\$\$$", item_content)
            if math_in_num:
                # Place number and rendered equation side-by-side using a table
                img = _render_latex(math_in_num.group(1), fontsize=12, display=True)
                if img:
                    num_para = Paragraph(f"{num}.", styles["numbered"])
                    tbl = Table(
                        [[num_para, img]],
                        colWidths=[10 * mm, None],
                    )
                    tbl.setStyle(TableStyle([
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]))
                    flowables.append(Spacer(1, 1.5 * mm))
                    flowables.append(tbl)
                    flowables.append(Spacer(1, 1.5 * mm))
                else:
                    flowables.append(Paragraph(_safe(item_content), styles["code"]))
            else:
                item_text = _inline_format(item_content)
                flowables.append(Paragraph(
                    item_text, styles["numbered"],
                    bulletText=f"{num}.",
                ))
            i += 1
            continue

        # ── Horizontal rule: --- or *** ──
        if re.match(r"^[\-\*\_]{3,}$", stripped):
            flowables.append(HRFlowable(
                width="100%", thickness=0.5,
                color=DIVIDER, spaceBefore=3 * mm, spaceAfter=3 * mm,
            ))
            i += 1
            continue

        # ── Check if entire line is a standalone math expression ($...$) ──
        standalone_math = re.match(r"^\$([^$]+)\$$", stripped)
        if standalone_math:
            img = _render_latex(standalone_math.group(1), fontsize=12, display=True)
            if img:
                # Reduced spacing before and after standalone inline math
                flowables.append(Spacer(1, 0.5 * mm))
                img.hAlign = 'LEFT' # Ensure ReportLab aligns the image to the left
                flowables.append(img)
                flowables.append(Spacer(1, 0.5 * mm))
                i += 1
                continue

        # ── Regular paragraph ──
        para_text = _inline_format(stripped)
        flowables.append(Paragraph(para_text, styles["body"]))
        i += 1

    return flowables


# ═══════════════════════════════════════════════════════════════════
# HEADER & FOOTER (drawn on every page via canvas callbacks)
# ═══════════════════════════════════════════════════════════════════

def _draw_header(canvas, doc):
    """Draw a centered branded header bar with 4 text lines at the top of every page."""
    canvas.saveState()

    header_height = 17 * mm
    top_y = PAGE_H

    # Blue accent bar at very top
    canvas.setFillColor(PRIMARY)
    canvas.rect(0, top_y - header_height, PAGE_W, header_height, fill=True, stroke=False)
    
    # ----- 1. Chat Icon (Left side) -----
    icon_x = MARGIN_LEFT
    bubble_w = 8.5 * mm
    bubble_h = 6.5 * mm
    bubble_x = icon_x
    bubble_y = top_y - 11.5 * mm
    
    # Chat bubble background
    canvas.setFillColor(ACCENT)
    canvas.roundRect(bubble_x, bubble_y, bubble_w, bubble_h, radius=1.5*mm, fill=True, stroke=False)
    
    # Chat bubble tail (triangle pointing down-left)
    p = canvas.beginPath()
    p.moveTo(bubble_x + 1.5*mm, bubble_y)
    p.lineTo(bubble_x + 1.5*mm, bubble_y - 2*mm)
    p.lineTo(bubble_x + 3.5*mm, bubble_y + 0.5*mm)
    canvas.drawPath(p, fill=True, stroke=False)
    
    # White dots inside the bubble
    canvas.setFillColor(WHITE)
    dot_y = bubble_y + 3.25 * mm
    canvas.circle(bubble_x + 2.5*mm, dot_y, 0.6*mm, fill=True, stroke=False)
    canvas.circle(bubble_x + 4.25*mm, dot_y, 0.6*mm, fill=True, stroke=False)
    canvas.circle(bubble_x + 6.0*mm, dot_y, 0.6*mm, fill=True, stroke=False)

    # ----- 2. EduBot Typography -----
    text_x = bubble_x + bubble_w + 3.5 * mm
    
    # Main Title
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(text_x, top_y - 8.5 * mm, "EduBot")
    
    # Subtitle
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#E2E8F0")) # Slightly dimmed white/light gray
    canvas.drawString(text_x, top_y - 13.5 * mm, "AI-powered study companion")

    # ----- 3. WhatsApp Bot Pill (Right side) -----
    pill_w = 26 * mm
    pill_h = 6.5 * mm
    pill_x = PAGE_W - MARGIN_RIGHT - pill_w
    pill_y = top_y - 12 * mm
    
    # Pill background
    canvas.setFillColor(ACCENT)
    canvas.roundRect(pill_x, pill_y, pill_w, pill_h, radius=3.25*mm, fill=True, stroke=False)
    
    # Pill text
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawCentredString(pill_x + pill_w/2, pill_y + 2.0*mm, "WhatsApp Bot")

    canvas.restoreState()


def _draw_footer(canvas, doc):
    """Draw a clean footer with page number."""
    canvas.saveState()

    y = 12 * mm

    # Thin line above footer
    canvas.setStrokeColor(DIVIDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_LEFT, y + 2 * mm, PAGE_W - MARGIN_RIGHT, y + 2 * mm)

    # Page number centered
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(LIGHT_TEXT)
    canvas.drawCentredString(PAGE_W / 2, y - 2 * mm, f"Page {doc.page}")

    canvas.restoreState()


def _draw_header_and_footer(canvas, doc):
    _draw_header(canvas, doc)
    _draw_footer(canvas, doc)


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def generate_pdf(title: str, content: str) -> str:
    """
    Generate a professionally styled PDF from a title and markdown content.
    Returns the absolute path to the generated temporary PDF file.
    """
    styles = _build_styles()

    # Create a temporary file for the output
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="edu_bot_")
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        author="Educational Assistant",
    )

    # Build the story (list of flowables)
    story = []

    # No title block — jump straight into the content.
    # The header bar already shows "Educational Assistant" and the date.

    # ── Parse and add the markdown body content ──
    body_flowables = _parse_markdown(content, styles)
    story.extend(body_flowables)

    # ── Build the PDF with header/footer on every page ──
    doc.build(
        story,
        onFirstPage=_draw_header_and_footer,
        onLaterPages=_draw_header_and_footer,
    )

    return tmp_path
