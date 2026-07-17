"""
EPUB parsing: pull readable text out of an .epub and split it into chapters.

We do two things:
  1. Extract each document in spine order and clean it to plain text.
  2. Try to detect chapter boundaries so the user gets a sensible starting
     point. They can always edit, merge, split, or rename afterwards.
"""

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from ebooklib import epub
import ebooklib

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


@dataclass
class Chapter:
    title: str
    text: str
    # order is assigned by the caller after any manual edits
    order: int = 0


@dataclass
class ParsedBook:
    title: str
    author: str
    chapters: list = field(default_factory=list)


# Headings we treat as a likely chapter start when auto-detecting.
_HEADING_TAGS = ("h1", "h2", "h3")


def _clean_html_to_text(html: str) -> str:
    """Strip tags and collapse whitespace, keeping paragraph breaks."""
    soup = BeautifulSoup(html, "lxml")

    for bad in soup(["script", "style"]):
        bad.decompose()

    # Turn block elements into newline-separated text so paragraphs survive.
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # Collect text from block elements — but never emit the same words twice.
    # A chapter wrapped in a container (the very common
    # `<div><p>…</p><p>…</p></div>`) would otherwise be emitted twice: once via
    # the outer div's get_text(), then again via each inner p. That doubled text
    # gets narrated twice, so every chapter is read out two times.
    #
    # For each block we take only its OWN direct text (the text belonging to it
    # rather than to a nested block). That keeps each passage exactly once, in
    # document order, while still catching loose text sitting directly inside a
    # container alongside its paragraphs.
    # Blocks we emit text for. CONTAINERS are elements that only wrap other
    # blocks (lists, tables, sections); they're never emitted themselves, but
    # they must be recognised so an enclosing div doesn't swallow their text
    # and repeat it. Missing one here means every item inside it gets read twice.
    BLOCKS = ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li",
              "blockquote", "pre", "figcaption", "dt", "dd", "td", "th"]
    CONTAINERS = ["ul", "ol", "table", "thead", "tbody", "tr", "dl",
                  "section", "article", "main", "aside", "nav", "header",
                  "footer", "figure"]
    SKIP_INSIDE = BLOCKS + CONTAINERS
    blocks = []
    for el in soup.find_all(BLOCKS):
        parts = []
        for child in el.children:
            # Skip nested blocks/containers — they're emitted on their own pass.
            if getattr(child, "name", None) in SKIP_INSIDE:
                continue
            piece = (child.get_text(" ", strip=True)
                     if getattr(child, "name", None)
                     else str(child).strip())
            if piece:
                parts.append(piece)
        chunk = " ".join(parts).strip()
        if chunk:
            blocks.append(chunk)

    if not blocks:
        # Fallback: whole-document text.
        blocks = [soup.get_text(" ", strip=True)]

    text = "\n\n".join(blocks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ordered_documents(book):
    """Yield the book's document items in spine (reading) order.

    ebooklib's get_items_of_type() returns items in *manifest* order, which
    often interleaves front/back matter oddly and isn't the order a person sees
    in an e-reader. The spine is the actual reading order, so we follow it and
    only fall back to manifest order for the rare document not listed in the
    spine. This makes the chapter list deterministic and sensibly ordered.
    """
    seen = set()
    spine = getattr(book, "spine", None) or []
    for entry in spine:
        idref = entry[0] if isinstance(entry, (tuple, list)) else entry
        if not idref:
            continue
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        if id(item) in seen:
            continue
        seen.add(id(item))
        yield item
    # Any document the spine didn't reference (uncommon) — keep it, in
    # manifest order, so nothing is silently dropped.
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if id(item) not in seen:
            seen.add(id(item))
            yield item


def _guess_title(html: str, fallback: str) -> str:
    """Use the first heading as a chapter title if there is one."""
    soup = BeautifulSoup(html, "lxml")
    for tag in _HEADING_TAGS:
        h = soup.find(tag)
        if h:
            t = h.get_text(" ", strip=True)
            if t:
                return t[:120]
    return fallback


def parse_epub(path: str) -> ParsedBook:
    """Read an epub and return one Chapter per spine document.

    Each spine item usually corresponds to one chapter in well-made epubs.
    For messy epubs the user can re-split in the UI.
    """
    book = epub.read_epub(path)

    title = "Untitled"
    author = "Unknown"
    if book.get_metadata("DC", "title"):
        title = book.get_metadata("DC", "title")[0][0]
    if book.get_metadata("DC", "creator"):
        author = book.get_metadata("DC", "creator")[0][0]

    chapters = []
    index = 0
    for item in _ordered_documents(book):
        # Skip the navigation document (epub3 nav / ncx toc).
        if getattr(item, "is_chapter", lambda: True)() is False:
            continue
        name = (item.get_name() or "").lower()
        if "nav" in name or "toc" in name or "contents" in name:
            continue

        html = item.get_content().decode("utf-8", errors="ignore")
        # A nav doc is mostly an <ol>/<nav> of links — detect and skip.
        low = html.lower()
        if "<nav" in low or 'epub:type="toc"' in low:
            continue

        text = _clean_html_to_text(html)

        # Skip near-empty documents (covers, blank pages, nav).
        if len(text) < 50:
            continue

        index += 1
        guessed = _guess_title(html, f"Chapter {index}")
        chapters.append(Chapter(title=guessed, text=text, order=index))

    # Re-number cleanly in case some items were skipped.
    for i, ch in enumerate(chapters, start=1):
        ch.order = i

    return ParsedBook(title=title, author=author, chapters=chapters)
