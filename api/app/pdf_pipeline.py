from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Callable

import fitz
from PIL import Image

from .models import PageImage, SourceBlock, SourceWord


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
            words = extract_text_words(page, index, blocks)
        else:
            progress(25 + int(index / total * 15), f"OCR page {index}/{total}")
            blocks, words = extract_ocr_content(image_path, index, float(page.rect.width), float(page.rect.height))
            extraction_method = "ocr"

        pages.append(
            PageImage(
                page_number=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                image_name=image_name,
                extraction_method=extraction_method,
                blocks=blocks,
                words=words,
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


def extract_text_words(page: fitz.Page, page_number: int, blocks: list[SourceBlock]) -> list[SourceWord]:
    words: list[SourceWord] = []
    for item in page.get_text("words"):
        if len(item) < 5:
            continue
        x0, y0, x1, y1, raw_text = item[:5]
        text = normalize_word(str(raw_text))
        if not text:
            continue
        bbox = [float(x0), float(y0), float(x1), float(y1)]
        words.append(
            SourceWord(
                page_number=page_number,
                block_id=find_block_id(bbox, blocks),
                text=text,
                bbox=bbox,
            )
        )
    return words


def extract_ocr_content(
    image_path: Path,
    page_number: int,
    page_width: float,
    page_height: float,
) -> tuple[list[SourceBlock], list[SourceWord]]:
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
    image_width, image_height = image.size
    scale_x = page_width / max(1, image_width)
    scale_y = page_height / max(1, image_height)
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
    source_words: list[SourceWord] = []
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
        block_id = f"p{page_number:04d}-o{block_index:04d}"
        block_bbox = scale_bbox(
            [
                min(float(word["left"]) for word in words),
                min(float(word["top"]) for word in words),
                max(float(word["right"]) for word in words),
                max(float(word["bottom"]) for word in words),
            ],
            scale_x,
            scale_y,
        )
        blocks.append(
            SourceBlock(
                page_number=page_number,
                block_id=block_id,
                source_text=text,
                bbox=block_bbox,
                confidence=confidence,
                warnings=warnings,
            )
        )
        for word in words:
            word_text = normalize_word(str(word["text"]))
            if not word_text:
                continue
            source_words.append(
                SourceWord(
                    page_number=page_number,
                    block_id=block_id,
                    text=word_text,
                    bbox=scale_bbox(
                        [
                            float(word["left"]),
                            float(word["top"]),
                            float(word["right"]),
                            float(word["bottom"]),
                        ],
                        scale_x,
                        scale_y,
                    ),
                    confidence=float(word["conf"]) if float(word["conf"]) >= 0 else None,
                )
            )

    if not blocks:
        raise RuntimeError(f"OCR produced no readable text on page {page_number}.")
    return blocks, source_words


def find_block_id(word_bbox: list[float], blocks: list[SourceBlock]) -> str:
    if not blocks:
        return ""
    center_x = (word_bbox[0] + word_bbox[2]) / 2
    center_y = (word_bbox[1] + word_bbox[3]) / 2
    for block in blocks:
        if len(block.bbox) != 4:
            continue
        x0, y0, x1, y1 = block.bbox
        if x0 <= center_x <= x1 and y0 <= center_y <= y1:
            return block.block_id
    return blocks[0].block_id


def scale_bbox(bbox: list[float], scale_x: float, scale_y: float) -> list[float]:
    return [bbox[0] * scale_x, bbox[1] * scale_y, bbox[2] * scale_x, bbox[3] * scale_y]


def normalize_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_word(value: str) -> str:
    value = value.replace("\x00", "").strip()
    if not value:
        return ""
    if not re.search(r"[A-Za-z0-9]", value):
        return ""
    return value
