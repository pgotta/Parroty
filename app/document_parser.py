"""
Parse non-EPUB documents (.txt, .md, .pdf, .doc, .docx, .rtf, .html) into the
same ParsedBook / Chapter structure the rest of Parroty uses.

Each format extracts readable text and makes a best-effort attempt to detect
chapter boundaries. Detection is heuristic — the user can always edit, merge,
split, or rename chapters afterwards, exactly as with EPUB.

Detection signals by format:
  - docx: paragraphs styled as Heading 1/2/3 (or "Title") start a chapter.
  - pdf:  lines that look like chapter headings ("Chapter 3", "PART II",
          all-caps short lines, or numbered headings).
  - txt/md: Markdown headings (#), or short stand-alone lines separated by
          blank lines that look like titles; falls back to blank-line blocks.
  - html: <h1>/<h2>/<h3> headings.
"""

import os
import re
import warnings

from .epub_parser import Chapter, ParsedBook


# ---- shared heading heuristics ------------------------------------------

# Lines that strongly look like a chapter heading regardless of format.
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*chapter\s+(\d+|[ivxlcdm]+|one|two|three|four|five|six|"
               r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
               r"|sixteen|seventeen|eighteen|nineteen|twenty)\b", re.I),
    re.compile(r"^\s*part\s+(\d+|[ivxlcdm]+|one|two|three|four|five)\b", re.I),
    re.compile(r"^\s*(prologue|epilogue|introduction|preface|foreword|"
               r"afterword|appendix|acknowledgments?|contents|index)\s*$", re.I),
    re.compile(r"^\s*\d+\.?\s+[A-Z]"),          # "1. Something" / "12 Title"
]


def _looks_like_heading(line: str) -> bool:
    """Heuristic: does this single line look like a chapter heading?"""
    s = line.strip()
    if not s or len(s) > 80:
        return False
    for pat in _CHAPTER_PATTERNS:
        if pat.match(s):
            return True
    # Short, title-like line: few words, mostly title/upper case, no end period.
    words = s.split()
    if 1 <= len(words) <= 8 and not s.endswith((".", ",", ";", ":", "!", "?")):
        letters = [c for c in s if c.isalpha()]
        if letters:
            upper_ratio = sum(c.isupper() for c in letters) / len(letters)
            # ALL CAPS, or Title Case (most words capitalized).
            if upper_ratio > 0.6:
                return True
            cap_words = sum(1 for w in words if w[:1].isupper())
            if cap_words >= max(1, len(words) - 1) and len(words) <= 6:
                return True
    return False


def _chapters_from_blocks(blocks, force_heading_flags=None):
    """Build chapters from a list of text blocks. `force_heading_flags`, if
    given, is a parallel list of booleans marking which blocks are headings
    (used by docx/html where styling tells us definitively). Otherwise we use
    the heuristic on each block's first line."""
    chapters = []
    cur_title = None
    cur_parts = []

    def flush():
        if cur_parts:
            body = "\n\n".join(p for p in cur_parts if p.strip()).strip()
            if body:
                chapters.append(Chapter(
                    title=cur_title or f"Chapter {len(chapters) + 1}",
                    text=body, order=len(chapters) + 1))

    for i, block in enumerate(blocks):
        text = block.strip()
        if not text:
            continue
        is_heading = (force_heading_flags[i] if force_heading_flags
                      else _looks_like_heading(text.split("\n", 1)[0]))
        if is_heading:
            # Heading starts a new chapter. Use the heading line as the title.
            flush()
            cur_title = text.split("\n", 1)[0].strip()[:120]
            cur_parts = []
            # If the heading block has body text after the first line, keep it.
            rest = text.split("\n", 1)[1].strip() if "\n" in text else ""
            if rest:
                cur_parts.append(rest)
        else:
            cur_parts.append(text)

    flush()
    if not chapters:
        # Nothing detected — one chapter with everything.
        whole = "\n\n".join(b.strip() for b in blocks if b.strip()).strip()
        chapters = [Chapter(title="Chapter 1", text=whole, order=1)]
    return chapters


# ---- per-format extraction ----------------------------------------------

def _parse_txt(path: str, title: str) -> ParsedBook:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Markdown headings take priority if present.
    if re.search(r"^#{1,6}\s+\S", raw, re.M):
        blocks, flags = [], []
        # Split so each heading line becomes its own block.
        for para in re.split(r"\n\s*\n", raw):
            para = para.strip("\n")
            if not para.strip():
                continue
            m = re.match(r"^(#{1,6})\s+(.*)", para)
            if m:
                blocks.append(m.group(2).strip())
                flags.append(True)
            else:
                blocks.append(para)
                flags.append(False)
        chapters = _chapters_from_blocks(blocks, flags)
        return ParsedBook(title=title, author="", chapters=chapters)

    # Otherwise split into blank-line-separated paragraphs and use heuristics.
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not paras:
        paras = [raw.strip()]
    chapters = _chapters_from_blocks(paras)
    return ParsedBook(title=title, author="", chapters=chapters)


def _parse_docx(path: str, title: str) -> ParsedBook:
    import docx
    doc = docx.Document(path)

    # Try document title/author from core properties.
    try:
        cp = doc.core_properties
        doc_title = (cp.title or "").strip() or title
        author = (cp.author or "").strip()
    except Exception:
        doc_title, author = title, ""

    blocks, flags = [], []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        is_heading = ("heading" in style or style == "title")
        # Some docs don't use heading styles — fall back to the heuristic.
        if not is_heading and _looks_like_heading(text):
            is_heading = True
        blocks.append(text)
        flags.append(is_heading)

    chapters = _chapters_from_blocks(blocks, flags)
    return ParsedBook(title=doc_title, author=author, chapters=chapters)


def _parse_pdf(path: str, title: str) -> ParsedBook:
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        meta_title = (pdf.metadata or {}).get("Title") if pdf.metadata else None
        meta_author = (pdf.metadata or {}).get("Author") if pdf.metadata else None
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln in text.split("\n"):
                lines.append(ln)

    # Group lines into paragraph blocks, flagging heading-like lines.
    blocks, flags = [], []
    buf = []
    for ln in lines:
        s = ln.strip()
        if not s:
            if buf:
                blocks.append(" ".join(buf)); flags.append(False); buf = []
            continue
        if _looks_like_heading(s):
            if buf:
                blocks.append(" ".join(buf)); flags.append(False); buf = []
            blocks.append(s); flags.append(True)
        else:
            buf.append(s)
    if buf:
        blocks.append(" ".join(buf)); flags.append(False)

    chapters = _chapters_from_blocks(blocks, flags)
    return ParsedBook(title=(meta_title or title), author=(meta_author or ""),
                      chapters=chapters)


def _parse_html(path: str, title: str) -> ParsedBook:
    from bs4 import BeautifulSoup
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    for bad in soup(["script", "style"]):
        bad.decompose()
    doc_title = (soup.title.get_text(strip=True) if soup.title else "") or title

    blocks, flags = [], []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "div", "li"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        blocks.append(text)
        flags.append(el.name in ("h1", "h2", "h3", "h4"))
    chapters = _chapters_from_blocks(blocks, flags)
    return ParsedBook(title=doc_title, author="", chapters=chapters)


def _parse_doc(path: str, title: str) -> ParsedBook:
    """Legacy .doc (binary Word). Try textract/antiword; fall back to a clear
    error if no extractor is available."""
    text = None
    try:
        import textract
        text = textract.process(path).decode("utf-8", errors="replace")
    except Exception:
        # Try antiword via subprocess if installed.
        try:
            import subprocess
            out = subprocess.run(["antiword", path], capture_output=True)
            if out.returncode == 0:
                text = out.stdout.decode("utf-8", errors="replace")
        except Exception:
            text = None
    if not text:
        raise ValueError(
            "Old-style .doc files need conversion. Please save it as .docx "
            "(File → Save As → Word Document) or .pdf and upload that instead.")
    # Reuse the txt path on the extracted text.
    tmp_blocks = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chapters = _chapters_from_blocks(tmp_blocks or [text.strip()])
    return ParsedBook(title=title, author="", chapters=chapters)


# ---- dispatcher ----------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown",
    ".pdf",
    ".doc", ".docx",
    ".rtf",
    ".htm", ".html",
}


def parse_document(path: str) -> ParsedBook:
    """Parse any supported non-EPUB document into a ParsedBook. Raises
    ValueError with a friendly message for unsupported or unreadable files."""
    ext = os.path.splitext(path)[1].lower()
    # A sensible default title from the filename.
    base_title = os.path.splitext(os.path.basename(path))[0]
    base_title = re.sub(r"[_\-]+", " ", base_title).strip().title() or "Document"

    if ext in (".txt", ".text", ".md", ".markdown"):
        return _parse_txt(path, base_title)
    if ext == ".pdf":
        return _parse_pdf(path, base_title)
    if ext == ".docx":
        return _parse_docx(path, base_title)
    if ext == ".doc":
        return _parse_doc(path, base_title)
    if ext == ".rtf":
        # RTF: strip control words to plain text, then treat as txt.
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        text = re.sub(r"\\[a-z]+-?\d* ?", " ", raw)
        text = re.sub(r"[{}]", "", text)
        tmp = path + ".txt"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            return _parse_txt(tmp, base_title)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if ext in (".htm", ".html"):
        return _parse_html(path, base_title)

    raise ValueError(f"Unsupported file type: {ext}. Supported: EPUB, TXT, MD, "
                     f"PDF, DOC, DOCX, RTF, HTML.")
