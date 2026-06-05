from __future__ import annotations

import html
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
            <article class="translation-block">
              <div class="block-meta">#{escape(block.block_id)}</div>
              <p class="translation">{escape(block.translation) or "<span class='muted'>未返回译文</span>"}</p>
              <details>
                <summary>原文</summary>
                <p>{escape(block.source_text)}</p>
              </details>
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
                <img src="/jobs/{escape(document.job_id)}/assets/{escape(page.image_name)}" alt="Original page {page.page_number}" />
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
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="meta">{provider} · {model} · 双语对页版</div>
  </header>
  {glossary}
  <main>
    {spreads}
  </main>
</body>
</html>
"""
