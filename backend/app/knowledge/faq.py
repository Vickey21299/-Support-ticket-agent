"""Parse faq.md into sections F01..F12 plus the client's rules. This is the agent's only knowledge."""
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_SECTION = re.compile(r"^##\s+(F\d{2})\s*\S\s*(.+?)\s*$")
_RULES_HEADER = re.compile(r"^##\s+The client's rules", re.IGNORECASE)
_HOST = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:nl|com|de|eu|io|net|org|app))\b", re.IGNORECASE)


@dataclass
class FaqSection:
    id: str
    title: str
    text: str


@dataclass
class Knowledge:
    sections: dict[str, FaqSection]
    client_rules: str
    allowed_hosts: set[str] = field(default_factory=set)

    def render(self, ids=None) -> str:
        ids = ids or list(self.sections)
        return "\n\n".join(
            f"[{s.id}] {s.title}\n{s.text}" for i in ids if (s := self.sections.get(i))
        )


def parse_faq(text: str) -> Knowledge:
    sections: dict[str, FaqSection] = {}
    rules_lines: list[str] = []
    current = None
    buf: list[str] = []
    in_rules = False

    def flush():
        if current:
            sections[current[0]] = FaqSection(current[0], current[1], "\n".join(buf).strip())

    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            flush()
            current, buf, in_rules = (m.group(1), m.group(2)), [], False
            continue
        if _RULES_HEADER.match(line):
            flush()
            current, buf, in_rules = None, [], True
            continue
        if line.strip() == "---":
            continue
        if in_rules:
            rules_lines.append(line)
        elif current:
            buf.append(line)
    flush()

    hosts = {h.lower() for h in _HOST.findall(text)}
    return Knowledge(sections, "\n".join(rules_lines).strip(), hosts)


@lru_cache
def load_knowledge(path: str) -> Knowledge:
    kb = parse_faq(Path(path).read_text(encoding="utf-8"))
    if len(kb.sections) < 1:
        raise RuntimeError(f"No FAQ sections found in {path}")
    return kb
