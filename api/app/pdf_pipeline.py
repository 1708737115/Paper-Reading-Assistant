from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Callable

import fitz
from PIL import Image

from .models import PageImage, SourceBlock


TEXT_MIN_CHARS = 80


def extract_pdf_pages(pdf_path: Path, job_dir: Path, progress: Callable[[int, str], None]) -> list[PageImage]:
    assets_dir = job_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    document = fitz.open(pdf_path)
    pages: list[PageImage] = []
    total = max(1, document.page_count)

    for index, page in enumerate(document, start=1):
        progress(5 + int(index / total * 25), f"Rendering page {index}/{total}")
        image_name = f"page_{index:04d}.png"
        image_path = assets_dir / image_name
        render_page_image(page, image_path)

        text_blocks = extract_text_layer(page, index)
        if sum(len(block.source_text) for block in text_blocks) >= TEXT_MIN_CHARS:
            extraction_method = "text-layer"
            blocks = text_blocks
        else:
            progress(25 + int(index / total * 15), f"OCR page {index}/{total}")
            blocks = extract_ocr_blocks(image_path, index)
            extraction_method = "ocr"

        pages.append(
            PageImage(
                page_number=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                image_name=image_name,
                extraction_method=extraction_method,
                blocks=blocks,
            )
        )

    document.close()
    return pages


def render_page_image(page: fitz.Page, output_path: Path) -> None:
    matrix = fitz.Matrix(2, 2)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    pixmap.save(output_path)


def extract_text_layer(page: fitz.Page, page_number: int) -> list[SourceBlock]:
    raw_blocks = page.get_text("blocks")
    blocks: list[SourceBlock] = []
    for block_index, item in enumerate(raw_blocks, start=1):
        if len(item) < 5:
            continue
        x0, y0, x1, y1, text = item[:5]
        normalized = normalize_text(str(text))
        if len(normalized) < 20:
            continue
        blocks.append(
            SourceBlock(
                page_number=page_number,
                block_id=f"p{page_number:04d}-b{block_index:04d}",
                source_text=normalized,
                bbox=[float(x0), float(y0), float(x1), float(y1)],
            )
        )
    return blocks


def extract_ocr_blocks(image_path: Path, page_number: int) -> list[SourceBlock]:
    if not shutil.which("tesseract"):
        raise RuntimeError(
            "This PDF page has no embedded text layer and Tesseract OCR is not available. "
            "Install Tesseract 5 and make sure the tesseract executable is on PATH."
        )

    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise RuntimeError("pytesseract is not installed. Run pip install -r api/requirements.txt.") from exc

    image = Image.open(image_path)
    data = pytesseract.image_to_data(image, lang="eng", output_type=Output.DICT, config="--psm 4")
    grouped: dict[tuple[int, int], list[dict[str, float | str]]] = defaultdict(list)

    for i, raw_text in enumerate(data.get("text", [])):
        text = normalize_text(raw_text)
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < 35:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]))
        grouped[key].append(
            {
                "text": text,
                "left": float(data["left"][i]),
                "top": float(data["top"][i]),
                "right": float(data["left"][i] + data["width"][i]),
                "bottom": float(data["top"][i] + data["height"][i]),
                "conf": conf,
                "line": float(data["line_num"][i]),
            }
        )

    blocks: list[SourceBlock] = []
    for block_index, (_, words) in enumerate(sorted(grouped.items()), start=1):
        if not words:
            continue
        words.sort(key=lambda word: (word["line"], word["top"], word["left"]))
        text = normalize_text(" ".join(str(word["text"]) for word in words))
        if len(text) < 20:
            continue
        confidences = [float(word["conf"]) for word in words if float(word["conf"]) >= 0]
        confidence = sum(confidences) / len(confidences) if confidences else None
        warnings: list[str] = []
        if confidence is not None and confidence < 70:
            warnings.append("Low OCR confidence")
        blocks.append(
            SourceBlock(
                page_number=page_number,
                block_id=f"p{page_number:04d}-o{block_index:04d}",
                source_text=text,
                bbox=[
                    min(float(word["left"]) for word in words),
                    min(float(word["top"]) for word in words),
                    max(float(word["right"]) for word in words),
                    max(float(word["bottom"]) for word in words),
                ],
                confidence=confidence,
                warnings=warnings,
            )
        )

    if not blocks:
        raise RuntimeError(f"OCR produced no readable text on page {page_number}.")
    return blocks


def normalize_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
