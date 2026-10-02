from html.parser import HTMLParser
from typing import List

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "li":
            self._parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Converts a job description HTML snippet to readable plain text (stdlib only)."""
    if not html:
        return ""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    lines = [" ".join(line.split()) for line in extractor.text().splitlines()]
    out: List[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
