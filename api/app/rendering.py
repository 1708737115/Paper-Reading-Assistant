from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path

from .models import TranslationDocument


def write_preview(document: TranslationDocument, output_path: Path) -> None:
    by_page = defaultdict(list)
    for block in document.translations:
        by_page[block.page_number].append(block)

    glossary_html = ""
    if document.glossary:
        terms = "\n".join(
            f"<li><span>{escape(term.source)}</span><strong>{escape(term.target)}</strong></li>"
            for term in document.glossary[:40]
        )
        glossary_html = f"""
        <section class="glossary">
          <h2>术语表</h2>
          <ul>{terms}</ul>
        </section>
        """

    spreads = []
    for page in document.pages:
        blocks = by_page.get(page.page_number, [])
        block_html = "\n".join(
            f"""
            <article class="translation-block" data-block-id="{escape(block.block_id)}">
              <div class="block-meta">#{escape(block.block_id)}</div>
              <p class="translation">{escape(block.translation) or "<span class='muted'>未返回译文</span>"}</p>
              <p class="source-text" data-block-id="{escape(block.block_id)}">{interactive_source_text(block.source_text, block.block_id)}</p>
              {warnings_html(block.warnings)}
            </article>
            """
            for block in blocks
        )
        spreads.append(
            f"""
            <section class="spread">
              <div class="original-page">
                <div class="page-label">Page {page.page_number} · {escape(page.extraction_method)}</div>
                <div class="original-page-inner">
                  <img src="/jobs/{escape(document.job_id)}/assets/{escape(page.image_name)}" alt="Original page {page.page_number}" />
                  <div class="source-layer" aria-hidden="true">
                    {source_word_layer(page)}
                  </div>
                </div>
              </div>
              <div class="translated-page">
                <div class="page-label">第 {page.page_number} 页译文</div>
                {block_html or "<p class='muted'>这一页没有可翻译文本。</p>"}
              </div>
            </section>
            """
        )

    output_path.write_text(
        HTML_TEMPLATE.format(
            title=escape(document.filename),
            provider=escape(document.provider.value),
            model=escape(document.model),
            glossary=glossary_html,
            spreads="\n".join(spreads),
            lookup_json=script_json(
                {
                    "entries": [entry.model_dump() for entry in document.lookup_entries],
                    "translations": {block.block_id: block.translation for block in document.translations},
                }
            ),
        ),
        encoding="utf-8",
    )


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def warnings_html(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{escape(item)}</li>" for item in warnings)
    return f"<ul class='warnings'>{items}</ul>"


def interactive_source_text(source_text: str, block_id: str) -> str:
    parts: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[^\s]", source_text):
        if re.search(r"[A-Za-z0-9]", token):
            parts.append(
                f"<span class='source-token' data-block-id='{escape(block_id)}' "
                f"data-lookup-text='{escape(token)}'>{escape(token)}</span>"
            )
        else:
            parts.append(escape(token))
    return " ".join(parts)


def source_word_layer(page: object) -> str:
    words = getattr(page, "words", [])
    width = max(1.0, float(getattr(page, "width", 1.0)))
    height = max(1.0, float(getattr(page, "height", 1.0)))
    spans: list[str] = []
    for word in words:
        if len(word.bbox) != 4:
            continue
        x0, y0, x1, y1 = word.bbox
        left = max(0.0, min(100.0, x0 / width * 100))
        top = max(0.0, min(100.0, y0 / height * 100))
        word_width = max(0.4, min(100.0, (x1 - x0) / width * 100))
        word_height = max(0.4, min(100.0, (y1 - y0) / height * 100))
        spans.append(
            "<span class='source-word' "
            f"data-block-id='{escape(word.block_id)}' data-lookup-text='{escape(word.text)}' "
            f"style='left:{left:.4f}%;top:{top:.4f}%;width:{word_width:.4f}%;height:{word_height:.4f}%;'>"
            f"{escape(word.text)}</span>"
        )
    return "\n".join(spans)


def script_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} · 双语版</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1c232b;
      --muted: #667085;
      --line: #d9dee7;
      --panel: #f7f8fb;
      --accent: #0f766e;
      --warn: #a16207;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      color: var(--ink);
      background: #eef1f6;
      line-height: 1.65;
    }}
    header {{
      padding: 24px 32px 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      font-weight: 720;
      letter-spacing: 0;
    }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    .glossary {{
      margin: 20px auto;
      width: min(1180px, calc(100vw - 40px));
      padding: 18px 22px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .glossary h2 {{ margin: 0 0 12px; font-size: 16px; }}
    .glossary ul {{
      margin: 0;
      padding: 0;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 8px 16px;
      list-style: none;
    }}
    .glossary li {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px dashed var(--line);
      font-size: 13px;
    }}
    .spread {{
      width: min(1180px, calc(100vw - 40px));
      margin: 22px auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
      break-after: page;
    }}
    .original-page, .translated-page {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-height: 420px;
    }}
    .original-page img {{
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }}
    .original-page-inner {{
      position: relative;
    }}
    .source-layer {{
      position: absolute;
      inset: 0;
    }}
    .source-word {{
      position: absolute;
      display: block;
      overflow: hidden;
      color: transparent;
      border-radius: 2px;
      cursor: pointer;
      line-height: 1;
      user-select: text;
      white-space: nowrap;
    }}
    .source-word:hover {{
      background: rgba(15, 118, 110, 0.16);
      outline: 1px solid rgba(15, 118, 110, 0.35);
    }}
    .translated-page {{ padding: 14px 18px 20px; }}
    .page-label {{
      padding: 8px 12px;
      color: var(--muted);
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      font-size: 12px;
      line-height: 1.3;
    }}
    .translation-block {{
      padding: 14px 0;
      border-bottom: 1px solid var(--line);
    }}
    .translation-block:last-child {{ border-bottom: 0; }}
    .block-meta {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    p {{ margin: 0; }}
    .translation {{ font-size: 15px; }}
    details {{
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
    }}
    summary {{ cursor: pointer; }}
    .source-text {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
      border-left: 3px solid var(--line);
      padding-left: 10px;
    }}
    .source-token {{
      cursor: pointer;
      border-radius: 3px;
      padding: 0 1px;
    }}
    .source-token:hover {{
      color: var(--accent);
      background: rgba(15, 118, 110, 0.09);
    }}
    .lookup-popover {{
      position: fixed;
      z-index: 1000;
      width: min(360px, calc(100vw - 24px));
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 18px 45px rgba(28, 35, 43, 0.18);
      font-size: 13px;
    }}
    .lookup-title {{
      color: var(--accent);
      font-weight: 750;
      margin-bottom: 4px;
      overflow-wrap: anywhere;
    }}
    .lookup-meaning {{
      font-size: 15px;
      font-weight: 680;
      margin-bottom: 6px;
    }}
    .lookup-note {{
      color: var(--muted);
      line-height: 1.55;
    }}
    .warnings {{
      margin: 8px 0 0;
      padding-left: 18px;
      color: var(--warn);
      font-size: 12px;
    }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 900px) {{
      .spread {{ grid-template-columns: 1fr; width: min(720px, calc(100vw - 24px)); }}
      header {{ padding: 18px 16px 12px; }}
      .glossary {{ width: min(720px, calc(100vw - 24px)); }}
    }}
    @media print {{
      body {{ background: #fff; }}
      header, .glossary, .spread {{ width: 100%; margin: 0 0 10mm; }}
      .spread {{ gap: 8mm; break-after: page; }}
      .original-page, .translated-page {{ border-radius: 0; }}
      details {{ display: none; }}
      .source-layer, .lookup-popover {{ display: none; }}
    }}
  </style>
</head>
<body>
  <script id="lookup-data" type="application/json">{lookup_json}</script>
  <header>
    <h1>{title}</h1>
    <div class="meta">{provider} · {model} · 双语对页版</div>
  </header>
  {glossary}
  <main>
    {spreads}
  </main>
  <script>
    (() => {{
      const rawData = document.getElementById("lookup-data")?.textContent || "{{}}";
      const data = JSON.parse(rawData);
      const entries = Array.isArray(data.entries) ? data.entries : [];
      const translations = data.translations || {{}};
      const lookup = new Map();
      for (const entry of entries) {{
        const key = normalize(entry.source || "");
        if (key && !lookup.has(key)) lookup.set(key, entry);
      }}

      let popover = null;

      document.addEventListener("click", (event) => {{
        const target = event.target.closest?.(".source-token, .source-word, .source-text, .translation-block");
        if (!target) {{
          hidePopover();
          return;
        }}
        const selected = selectedSourceText();
        const text = selected || target.dataset.lookupText || "";
        if (!text.trim()) return;
        const blockNode = target.closest?.("[data-block-id]");
        const blockId = target.dataset.blockId || blockNode?.dataset.blockId || "";
        showLookup(text, blockId, event.clientX, event.clientY);
      }});

      document.addEventListener("keydown", (event) => {{
        if (event.key === "Escape") hidePopover();
      }});

      function showLookup(text, blockId, x, y) {{
        const entry = findEntry(text);
        const meaning = entry?.meaning || "未收录精确释义";
        const explanation = entry?.explanation || translations[blockId] || "可参考该段译文理解。";
        hidePopover();
        popover = document.createElement("aside");
        popover.className = "lookup-popover";
        popover.innerHTML = `
          <div class="lookup-title">${{escapeHtml(text.trim())}}</div>
          <div class="lookup-meaning">${{escapeHtml(meaning)}}</div>
          <div class="lookup-note">${{escapeHtml(explanation)}}</div>
        `;
        document.body.appendChild(popover);
        const margin = 12;
        const rect = popover.getBoundingClientRect();
        const left = Math.min(window.innerWidth - rect.width - margin, Math.max(margin, x + 12));
        const top = Math.min(window.innerHeight - rect.height - margin, Math.max(margin, y + 12));
        popover.style.left = `${{left}}px`;
        popover.style.top = `${{top}}px`;
      }}

      function findEntry(text) {{
        for (const key of variants(text)) {{
          const entry = lookup.get(key);
          if (entry) return entry;
        }}
        return null;
      }}

      function variants(text) {{
        const key = normalize(text);
        const values = new Set([key]);
        if (key.endsWith("ies") && key.length > 4) values.add(`${{key.slice(0, -3)}}y`);
        if (key.endsWith("es") && key.length > 3) values.add(key.slice(0, -2));
        if (key.endsWith("s") && key.length > 3) values.add(key.slice(0, -1));
        if (key.endsWith("ed") && key.length > 4) values.add(key.slice(0, -2));
        if (key.endsWith("ing") && key.length > 5) values.add(key.slice(0, -3));
        return [...values].filter(Boolean);
      }}

      function selectedSourceText() {{
        const selection = window.getSelection();
        if (!selection || selection.isCollapsed) return "";
        const text = selection.toString().trim();
        const node = selection.anchorNode?.parentElement;
        if (!node?.closest?.(".source-text, .source-layer")) return "";
        return text;
      }}

      function normalize(text) {{
        return String(text)
          .toLowerCase()
          .replace(/[“”"'.?!,;:()[\\]{{}}]/g, " ")
          .replace(/\\s+/g, " ")
          .trim();
      }}

      function escapeHtml(value) {{
        return String(value).replace(/[&<>"']/g, (char) => ({{
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#039;"
        }}[char]));
      }}

      function hidePopover() {{
        if (popover) popover.remove();
        popover = null;
      }}
    }})();
  </script>
</body>
</html>
"""
