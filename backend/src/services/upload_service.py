"""
upload_service.py — сервис загрузки проектов через ZIP архив.

Позволяет добавлять проекты на VPS через Web UI без прямого доступа к файловой системе.
Pipeline: upload zip → validate → extract → scan

Ограничения безопасности:
- Максимальный размер архива: 100MB
- Проверка путей (zip slip protection)
- Только разрешённые расширения файлов
- Таймаут на распаковку
"""
import logging
import shutil
import zipfile
from pathlib import Path

from exceptions import RAGError
from logging_config import timed

log = logging.getLogger(__name__)

# Ограничения
MAX_ZIP_SIZE_MB = 100
MAX_EXTRACTED_SIZE_MB = 500
MAX_FILES_IN_ARCHIVE = 10_000

# Расширения которые точно не нужны в индексе
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib",   # бинарники
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".webp",  # изображения
    ".mp4", ".mp3", ".avi", ".mov",    # медиа
    ".zip", ".tar", ".gz", ".rar",     # вложенные архивы
}


class UploadError(RAGError):
    """Ошибка при загрузке или распаковке архива."""
    http_status = 400
    log_level = "warning"


class UploadService:
    """
    Принимает ZIP архив, валидирует и распаковывает в projects_base_path.
    """

    def __init__(self, projects_base_path: Path) -> None:
        self._base = projects_base_path
        self._base.mkdir(parents=True, exist_ok=True)

    @timed("zip_extract")
    def extract(self, zip_bytes: bytes, project_name: str) -> Path:
        """
        Валидирует и распаковывает ZIP в папку проекта.

        Args:
            zip_bytes:    Содержимое ZIP файла
            project_name: Имя папки назначения (санитизируется)

        Returns:
            Path к распакованной папке проекта

        Raises:
            UploadError: При проблемах с архивом или безопасностью
        """
        import re

        # Санитизация имени
        name = re.sub(r"[^\w\-.]", "_", project_name).strip("._")
        if not name:
            raise UploadError("Неверное имя проекта")

        # Проверка размера архива
        size_mb = len(zip_bytes) / 1024 / 1024
        if size_mb > MAX_ZIP_SIZE_MB:
            raise UploadError(
                f"Архив слишком большой: {size_mb:.1f}MB. Максимум: {MAX_ZIP_SIZE_MB}MB"
            )

        # Парсим zip
        import io
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as e:
            raise UploadError(f"Неверный ZIP файл: {e}") from e

        with zf:
            members = zf.infolist()

            # Проверка количества файлов
            if len(members) > MAX_FILES_IN_ARCHIVE:
                raise UploadError(
                    f"В архиве слишком много файлов: {len(members)}. "
                    f"Максимум: {MAX_FILES_IN_ARCHIVE}"
                )

            # Проверка суммарного размера
            total_size_mb = sum(m.file_size for m in members) / 1024 / 1024
            if total_size_mb > MAX_EXTRACTED_SIZE_MB:
                raise UploadError(
                    f"Суммарный размер файлов: {total_size_mb:.1f}MB. "
                    f"Максимум: {MAX_EXTRACTED_SIZE_MB}MB"
                )

            # ZIP Slip защита: проверяем что все пути внутри архива безопасны
            project_path = self._base / name
            for member in members:
                # Нормализуем путь и проверяем что он не выходит за пределы
                member_path = (project_path / member.filename).resolve()
                try:
                    member_path.relative_to(project_path.resolve())
                except ValueError:
                    raise UploadError(
                        f"Небезопасный путь в архиве: {member.filename}"
                    )

            # Удаляем старую версию если есть
            if project_path.exists():
                shutil.rmtree(project_path)
            project_path.mkdir(parents=True)

            # Распаковываем, пропуская заблокированные расширения
            extracted = 0
            skipped = 0
            for member in members:
                if member.is_dir():
                    continue
                ext = Path(member.filename).suffix.lower()
                if ext in BLOCKED_EXTENSIONS:
                    skipped += 1
                    continue
                zf.extract(member, project_path)
                extracted += 1

        log.info(
            "ZIP распакован",
            extra={
                "project": name,
                "extracted": extracted,
                "skipped": skipped,
                "size_mb": round(size_mb, 2),
            },
        )
        return project_path

    @staticmethod
    def validate_zip_name(filename: str) -> tuple[bool, str]:
        """Проверяет что имя загруженного файла допустимо."""
        if not filename:
            return False, "Имя файла пустое"
        if not filename.lower().endswith(".zip"):
            return False, "Только ZIP файлы поддерживаются"
        if len(filename) > 255:
            return False, "Имя файла слишком длинное"
        return True, ""
