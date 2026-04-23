"""
upload.py — роутер загрузки проектов через ZIP.
POST /api/upload — принимает multipart/form-data, распаковывает и сканирует.
"""
import logging

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from dependencies import get_scanner
from middleware.error_handler import safe_sse_stream
from rate_limiter import limiter
from services.scanner import ProjectScanner
from services.upload_service import UploadError, UploadService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def get_upload_service(settings=Depends(__import__("config", fromlist=["get_settings"]).get_settings)):
    return UploadService(settings.projects_base_path)


@router.post("/zip")
@limiter.limit("5/minute")
async def upload_zip(
    request: Request,
    file: UploadFile = File(..., description="ZIP архив проекта"),
    project_name: str = Form(default="", description="Имя проекта (по умолчанию — имя файла без .zip)"),
    scanner: ProjectScanner = Depends(get_scanner),
    upload_svc: UploadService = Depends(get_upload_service),
) -> StreamingResponse:
    """
    Загрузить ZIP архив и сразу проиндексировать проект.

    SSE события: upload_start → upload_done → scan progress → done | error

    Ограничения:
    - Максимальный размер: 100MB
    - Только .zip файлы
    - ZIP slip защита
    - 5 запросов/минуту
    """
    # Определяем имя проекта
    name = project_name.strip()
    if not name and file.filename:
        name = file.filename.removesuffix(".zip").removesuffix(".ZIP")
    if not name:
        name = "uploaded_project"

    # Валидируем имя файла
    if file.filename:
        valid, err = UploadService.validate_zip_name(file.filename)
        if not valid:
            from exceptions import RAGError
            raise RAGError(err, http_status=400)

    async def _gen():
        yield {
            "type":     "upload_start",
            "filename": file.filename,
            "project":  name,
        }

        # Читаем файл в память (FastAPI UploadFile — это SpooledTemporaryFile)
        try:
            zip_bytes = await file.read()
        except Exception as exc:
            from exceptions import RAGError
            raise RAGError(f"Ошибка чтения файла: {exc}") from exc

        size_mb = round(len(zip_bytes) / 1024 / 1024, 2)
        log.info(
            "Получен ZIP файл",
            extra={"project": name, "filename": file.filename, "size_mb": size_mb},
        )

        # Распаковываем (синхронно — zipfile не async, но быстро)
        import asyncio
        project_path = await asyncio.get_event_loop().run_in_executor(
            None,
            upload_svc.extract,
            zip_bytes,
            name,
        )

        yield {
            "type":    "upload_done",
            "project": name,
            "path":    str(project_path),
            "size_mb": size_mb,
        }

        # Сразу сканируем
        async for progress in scanner.scan(project_path):
            yield progress.__dict__

    return StreamingResponse(
        safe_sse_stream(_gen(), f"upload:{name}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/limits")
async def upload_limits() -> dict:
    """Возвращает текущие ограничения на загрузку (для отображения в UI)."""
    return {
        "max_zip_size_mb":       100,
        "max_extracted_size_mb": 500,
        "max_files":             10_000,
        "allowed_formats":       [".zip"],
        "rate_limit":            "5/minute",
    }
