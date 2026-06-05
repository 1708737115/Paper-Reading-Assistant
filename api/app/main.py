from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv

from .job_store import JobStore
from .models import JobStatus, ProviderName, TranslationDocument, now_utc
from .pdf_pipeline import extract_pdf_pages
from .rendering import write_preview
from .translators import ProviderConfig, translate_blocks


load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data")).resolve()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

app = FastAPI(title="Bilingual Paper Reader API")
store = JobStore(DATA_DIR)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    provider: ProviderName = Form(...),
    model: str | None = Form(default=None),
    apiKey: str = Form(...),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    if not apiKey.strip():
        raise HTTPException(status_code=400, detail="API key is required.")

    job = store.create(file.filename, provider, model.strip() if model else None)
    try:
        with job.source_pdf.open("wb") as output:
            shutil.copyfileobj(file.file, output)
    finally:
        await file.close()

    background_tasks.add_task(run_job, job.id, provider, job.model, apiKey.strip())
    return job.public()


@app.get("/jobs")
def list_jobs():
    return store.list_public()


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.public()


@app.get("/jobs/{job_id}/preview")
def preview_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.completed or job.preview_html is None or not job.preview_html.exists():
        raise HTTPException(status_code=409, detail="Preview is not ready.")
    return HTMLResponse(job.preview_html.read_text(encoding="utf-8"))


@app.get("/jobs/{job_id}/assets/{asset_name}")
def job_asset(job_id: str, asset_name: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    asset_path = (job.job_dir / "assets" / Path(asset_name).name).resolve()
    if job.job_dir.resolve() not in asset_path.parents or not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(asset_path)


@app.get("/jobs/{job_id}/export.pdf")
async def export_pdf(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Job is not completed.")
    pdf_path = job.job_dir / "bilingual.pdf"
    if pdf_path.exists():
        return FileResponse(pdf_path, media_type="application/pdf", filename=f"{Path(job.filename).stem}-bilingual.pdf")

    try:
        await render_pdf_with_playwright(f"{PUBLIC_BASE_URL}/jobs/{job_id}/preview", pdf_path)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "PDF export requires Playwright Chromium. Run: python -m playwright install chromium",
                "error": str(exc),
            },
        )

    store.update(job_id, export_pdf=pdf_path)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{Path(job.filename).stem}-bilingual.pdf")


async def run_job(job_id: str, provider: ProviderName, model: str, api_key: str) -> None:
    progress = store.progress_updater(job_id)
    job = store.get(job_id)
    if job is None:
        return

    try:
        store.update(job_id, status=JobStatus.processing, progress=2, current_step="Starting")
        pages = await asyncio.to_thread(extract_pdf_pages, job.source_pdf, job.job_dir, progress)
        blocks = [block for page in pages for block in page.blocks]
        if not blocks:
            raise RuntimeError("No readable text blocks were found in this PDF.")

        store.update(job_id, pages=len(pages), progress=42, current_step="Preparing translation")
        glossary, translations = await translate_blocks(
            ProviderConfig(provider=provider, model=model, api_key=api_key),
            blocks,
            progress,
        )

        document = TranslationDocument(
            job_id=job_id,
            filename=job.filename,
            provider=provider,
            model=model,
            created_at=now_utc(),
            pages=pages,
            translations=translations,
            glossary=glossary,
        )
        manifest_path = job.job_dir / "document.json"
        manifest_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
        preview_path = job.job_dir / "preview.html"
        write_preview(document, preview_path)
        store.update(
            job_id,
            status=JobStatus.completed,
            progress=100,
            current_step="Completed",
            preview_html=preview_path,
            warnings=collect_warnings(document),
        )
    except Exception as exc:
        store.update(job_id, status=JobStatus.failed, progress=100, current_step="Failed", error=str(exc))


async def render_pdf_with_playwright(url: str, output_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        await page.goto(url, wait_until="networkidle")
        await page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={"top": "10mm", "right": "8mm", "bottom": "10mm", "left": "8mm"},
        )
        await browser.close()


def collect_warnings(document: TranslationDocument) -> list[str]:
    warnings: list[str] = []
    for page in document.pages:
        if page.extraction_method == "ocr":
            warnings.append(f"Page {page.page_number} used OCR")
    for block in document.translations:
        warnings.extend(block.warnings)
    return sorted(set(warnings))[:20]
