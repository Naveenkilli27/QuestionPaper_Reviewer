"""Question Paper Reviewer — structured CO, Bloom, duplication, and syllabus checks."""

from __future__ import annotations

import html
import shutil
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.parser import extract_text
from app.structured_review import build_three_step_review_markdown

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SET_LABELS = ("Set A", "Set B", "Set C", "Set D", "Set E")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Question Paper Reviewer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _utf8_safe(s: str) -> str:
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _parse_num_sets(raw: str) -> int:
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, n))


def _error_page(title: str, message: str, detail: str = "") -> str:
    esc_msg = html.escape(_utf8_safe(message))
    esc_det = html.escape(_utf8_safe(detail))
    det_block = f"<pre>{esc_det}</pre>" if detail else ""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'/>"
        f"<title>{html.escape(title)}</title>"
        "<link rel='stylesheet' href='/static/style.css'/>"
        "<style>body{font-family:system-ui,sans-serif;background:#0f1419;color:#e8eef5;"
        "padding:1.5rem;line-height:1.5}"
        "pre{overflow:auto;background:#1a222d;padding:1rem;border-radius:8px;font-size:.85rem}"
        "a{color:#3d9aed}</style></head><body>"
        "<p><a href='/'>← Back to form</a></p>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{esc_msg}</p>{det_block}"
        "</body></html>"
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    body = TEMPLATES.get_template("index.html").render(
        request=request,
        set_labels=SET_LABELS,
        max_sets=len(SET_LABELS),
        num_sets_prefill=1,
        error=None,
    )
    return HTMLResponse(content=_utf8_safe(body), media_type="text/html; charset=utf-8")


@app.get("/review", response_class=HTMLResponse)
async def review_get_hint() -> HTMLResponse:
    page = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<title>Use the form</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#0f1419;color:#e8eef5;"
        "padding:2rem;max-width:40rem}a{color:#3d9aed}</style></head><body>"
        "<h1>Use the home page form</h1>"
        "<p>Click <strong>Run review</strong> on the home page — "
        "do not type <code>/review</code> in the address bar directly.</p>"
        "<p><a href='/'>Go to home page</a></p></body></html>"
    )
    return HTMLResponse(content=page, media_type="text/html; charset=utf-8")


@app.post("/review", response_class=HTMLResponse)
async def review(
    request: Request,
    num_sets: str = Form("1"),
    course_name: str = Form(""),
    syllabus_units: str = Form(""),
    cos_text: str = Form(""),
    co_required: str | None = Form(None),
    bloom_in_paper: str | None = Form(None),
    set_a: UploadFile | None = File(None),
    set_b: UploadFile | None = File(None),
    set_c: UploadFile | None = File(None),
    set_d: UploadFile | None = File(None),
    set_e: UploadFile | None = File(None),
) -> HTMLResponse:

    n_sets = _parse_num_sets(num_sets)
    uploads = [set_a, set_b, set_c, set_d, set_e]
    session_dir = UPLOAD_DIR / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── 1. Save and extract all uploaded files ───────────────────────────
        extracted: list[tuple[str, str]] = []
        for i in range(n_sets):
            label = SET_LABELS[i]
            up = uploads[i]
            if up is None or not up.filename:
                return HTMLResponse(
                    content=_error_page(
                        "Missing file",
                        f"You declared {n_sets} set(s) but no file was uploaded for {label}. "
                        "Go back and attach a file for every set.",
                    ),
                    status_code=400,
                    media_type="text/html; charset=utf-8",
                )
            suffix = Path(up.filename).suffix.lower()
            if suffix not in {".pdf", ".docx", ".txt", ".md"}:
                return HTMLResponse(
                    content=_error_page(
                        "Unsupported file type",
                        f"{label}: '{suffix}' is not supported. Please use PDF, DOCX, or TXT.",
                    ),
                    status_code=400,
                    media_type="text/html; charset=utf-8",
                )
            dest = session_dir / f"{label.replace(' ', '_')}{suffix}"
            dest.write_bytes(await up.read())
            try:
                raw = extract_text(dest)
            except Exception as exc:
                return HTMLResponse(
                    content=_error_page(
                        "Could not read file",
                        f"Failed to extract text from {label} ({up.filename}): {exc}",
                        traceback.format_exc(),
                    ),
                    status_code=422,
                    media_type="text/html; charset=utf-8",
                )
            extracted.append((label, raw))

        # ── 2. Structured review (CO, Bloom, duplicates, syllabus) ───────────
        try:
            review_markdown = build_three_step_review_markdown(
                extracted_texts=extracted,
                cos_text=cos_text,
                syllabus_units=syllabus_units,
                bloom_in_paper=bloom_in_paper is not None,
                co_required=co_required is not None,
            )
        except Exception as exc:
            return HTMLResponse(
                content=_error_page(
                    "Review could not complete",
                    f"{type(exc).__name__}: {exc}",
                    traceback.format_exc(),
                ),
                status_code=500,
                media_type="text/html; charset=utf-8",
            )

        # ── 3. Render the report page ────────────────────────────────────────
        body = TEMPLATES.get_template("report.html").render(
            request=request,
            course_name=course_name or "(not specified)",
            sets_count=n_sets,
            review_markdown=review_markdown,
        )
        return HTMLResponse(
            content=_utf8_safe(body),
            media_type="text/html; charset=utf-8",
        )

    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
