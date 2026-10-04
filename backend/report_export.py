"""Export the UI/UX + performance report as a standalone HTML document.

The Markdown file is the source of truth; this turns it into one
self-contained HTML file (inline CSS, no scripts, no external requests) that
opens in any browser and prints to PDF cleanly. That matters for a local-first
product: a report that needs a build step or a CDN to read is a report nobody
reads.

    python report_export.py                     # md -> docs/reports/*.html
    python report_export.py --table             # print the results table
                                                # from bench_v3_results.json

No third-party markdown library is used because none is installed in the
frozen environment; the subset implemented here is exactly what the report
uses (headings, paragraphs, tables, lists, fenced code, quotes, rules,
bold/italic/code spans, links, images).
"""
from __future__ import annotations

import argparse

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_MD = REPO / "docs" / "UI_UX_AND_PERFORMANCE_REPORT.md"
DEFAULT_OUT = REPO / "docs" / "reports" / "terabit-studio-ui-ux-and-v3-performance.html"

CSS = """
:root { color-scheme: light dark; --ink:#14161c; --muted:#5b6379; --line:#e3e6ee;
        --accent:#6d4aff; --bg:#ffffff; --panel:#f7f8fc; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e8eaf6; --muted:#9aa3bd; --line:#262b3d; --accent:#a78bfa;
          --bg:#0b0d14; --panel:#12141f; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:16px/1.65 "Segoe UI", system-ui, -apple-system, sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 48px 24px 96px; }
h1 { font-size: 30px; line-height:1.25; margin: 0 0 8px; letter-spacing:-.02em; }
h2 { font-size: 22px; margin: 40px 0 12px; padding-top: 20px; border-top: 1px solid var(--line); }
h3 { font-size: 17px; margin: 28px 0 8px; }
h4 { font-size: 15px; margin: 20px 0 6px; color: var(--muted); }
p, li { color: var(--ink); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: var(--panel); border:1px solid var(--line); border-radius:6px;
       padding:1px 5px; font: 13.5px/1.5 "Cascadia Mono", Consolas, monospace; }
pre { background: var(--panel); border:1px solid var(--line); border-radius:12px;
      padding:14px 16px; overflow:auto; }
pre code { background:none; border:none; padding:0; }
blockquote { margin: 16px 0; padding: 8px 18px; border-left: 3px solid var(--accent);
             background: var(--panel); border-radius: 0 10px 10px 0; color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin: 18px 0; font-size: 14.5px; }
th, td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: var(--panel); font-weight: 600; }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--panel) 55%, transparent); }
hr { border: none; border-top: 1px solid var(--line); margin: 36px 0; }
img { max-width: 100%; border: 1px solid var(--line); border-radius: 12px; margin: 10px 0; }
nav.toc { background: var(--panel); border:1px solid var(--line); border-radius: 12px;
          padding: 16px 20px; margin: 24px 0 8px; font-size: 14.5px; }
nav.toc ol { margin: 6px 0 0; padding-left: 20px; }
nav.toc a { color: var(--ink); }
footer { margin-top: 48px; color: var(--muted); font-size: 13px; }
@media print {
  body { font-size: 11.5pt; }
  main { max-width: none; padding: 0; }
  h2 { break-after: avoid; page-break-after: avoid; }
  table, img, pre { break-inside: avoid; page-break-inside: avoid; }
  nav.toc { border: none; }
}
"""


def slug(text: str, seen: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-") or "section"
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}-{n}"


def inline(text: str) -> str:
    """Escape, then apply the inline subset. Code spans are protected first so
    that `**this**` inside backticks stays literal."""
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">',
                  text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
                  text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    for i, span in enumerate(spans):
        text = text.replace(f"\x00{i}\x00", span)
    return text


def convert(markdown_text: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = markdown_text.splitlines()
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {}
    i = 0
    in_code = False
    list_mode: str | None = None
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_mode
        if list_mode:
            out.append(f"</{list_mode}>")
            list_mode = None

    def open_list(kind: str) -> None:
        nonlocal list_mode
        if list_mode != kind:
            close_list()
            out.append(f"<{kind}>")
            list_mode = kind

    while i < len(lines):
        line = lines[i]

        if in_code:
            if line.strip().startswith("```"):
                out.append("</code></pre>")
                in_code = False
            else:
                out.append(html.escape(line))
            i += 1
            continue

        if line.strip().startswith("```"):
            flush_paragraph()
            close_list()
            out.append("<pre><code>")
            in_code = True
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            i += 1
            continue

        if re.match(r"^\|.*\|\s*$", line):
            flush_paragraph()
            close_list()
            rows: list[list[str]] = []
            while i < len(lines) and re.match(r"^\|.*\|\s*$", lines[i]):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                head, *body = rows
                out.append("<table><thead><tr>"
                           + "".join(f"<th>{inline(c)}</th>" for c in head)
                           + "</tr></thead><tbody>")
                for row in body:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
                out.append("</tbody></table>")
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            anchor = slug(heading.group(2), seen)
            if level <= 3:
                toc.append((level, anchor, inline(heading.group(2))))
            out.append(f'<h{level} id="{anchor}">{inline(heading.group(2))}</h{level}>')
            i += 1
            continue

        if re.match(r"^---+$", line.strip()):
            flush_paragraph()
            close_list()
            out.append("<hr>")
            i += 1
            continue

        if line.strip().startswith(">"):
            flush_paragraph()
            close_list()
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", line)
        number = re.match(r"^\d+[.)]\s+(.*)$", line)
        if bullet or number:
            flush_paragraph()
            open_list("ul" if bullet else "ol")
            out.append(f"<li>{inline((bullet or number).group(1))}</li>")
            i += 1
            continue

        paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    close_list()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out), toc


def build_html(body: str, toc: list[tuple[int, str, str]], title: str) -> str:
    toc_html = ""
    if toc:
        items = "".join(
            f'<li><a href="#{anchor}">{text}</a></li>' for level, anchor, text in toc if level == 2
        )
        toc_html = f'<nav class="toc"><strong>Contents</strong><ol>{items}</ol></nav>'
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{toc_html}\n{body}\n"
        "<footer>Generated from the Markdown report by backend/report_export.py — "
        "print with Ctrl+P for a PDF copy.</footer>\n</main>\n</body>\n</html>\n"
    )


def results_table(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = ["| Case | Task | Wall time | Files | Bundle | Tier | Brief facts kept |",
            "|---|---|---|---|---|---|---|"]
    for c in data.get("cases", []):
        if c.get("error"):
            rows.append(f"| {c['id']} | {c['label']} | failed | – | – | – | {c['error'][:60]} |")
            continue
        met = f"{c['expectations_met']}/{c['expectations_total']}"
        short = ", ".join(k for k, v in (c.get("expectations") or {}).items() if not v) or "all"
        rows.append(
            f"| `{c['id']}` | {c['label']} | {c['wall_s']:.0f} s "
            f"({c['wall_s'] / 60:.1f} min) | {c['files']} | "
            f"{'yes' if c.get('bundle_ok') else 'NO'} | {c.get('preview_tier')} | {met} — missing: {short} |"
        )
    rows.append("")
    rows.append(f"_Model: `{data.get('model')}` · context: {data.get('ctx')} tokens · "
                f"machine: {json.dumps(data.get('machine', {}))}_")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--table", action="store_true",
                    help="print the markdown results table and exit")
    args = ap.parse_args()

    if args.table:
        print(results_table(HERE / "bench_v3_results.json"))
        return 0

    if not args.md.is_file():
        print(f"report not found: {args.md}", file=sys.stderr)
        return 1
    text = args.md.read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip() if text.startswith("#") else "Report"
    body, toc = convert(text)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(body, toc, title), encoding="utf-8")
    print(f"exported -> {args.out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    # Windows consoles default to cp1252; the report and this table contain
    # model output and em dashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(main())
