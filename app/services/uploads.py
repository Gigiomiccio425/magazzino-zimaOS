"""Allegati: tipo riconosciuto dai byte (non dal nome), foto senza metadati, miniature, cestino manuale."""
import io
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Attachment
from ..timeutil import utcnow

MAX_BYTES = 25 * 1024 * 1024
THUMB_PX = 400
TRASH = ".cestino"
IMAGE_TYPES = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp"),
               "GIF": ("image/gif", ".gif")}
TEXT_EXT = {".txt": "text/plain", ".log": "text/plain", ".json": "application/json", ".csv": "text/csv"}
INLINE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}


class UploadRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def detect_kind(head: bytes, filename: str) -> tuple[str, str] | None:
    if head.startswith(b"\xff\xd8\xff"):
        return IMAGE_TYPES["JPEG"]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return IMAGE_TYPES["PNG"]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return IMAGE_TYPES["WEBP"]
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return IMAGE_TYPES["GIF"]
    if head.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    ext = Path(filename or "").suffix.lower()
    if ext in TEXT_EXT and b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            # l'inizio potrebbe tagliare un carattere multibyte: tolleriamo solo errori in coda
            try:
                head[:-4].decode("utf-8")
            except UnicodeDecodeError:
                return None
        lowered = head[:200].lower()
        if b"<html" in lowered or b"<script" in lowered or b"<svg" in lowered:
            return None
        return TEXT_EXT[ext], ext
    return None


def _clean_image(data: bytes) -> tuple[bytes, Image.Image]:
    """Applica la rotazione EXIF e risalva senza metadati (niente GPS)."""
    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        if fmt == "GIF":
            return data, img.copy()
        upright = ImageOps.exif_transpose(img)
        if fmt == "JPEG" and upright.mode not in ("RGB", "L"):
            upright = upright.convert("RGB")
        out = io.BytesIO()
        params = {"quality": 90} if fmt in ("JPEG", "WEBP") else {}
        upright.save(out, fmt, **params)
        return out.getvalue(), upright.copy()


def save_upload(settings: Settings, db: Session, upload: UploadFile, entity_type: str, entity_id: int,
                signer) -> Attachment:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise UploadRejected(413, f"File troppo grande (massimo {MAX_BYTES // (1024 * 1024)} MB).")
    kind = detect_kind(data[:4096], upload.filename or "")
    if not kind:
        raise UploadRejected(415, "Tipo di file non ammesso: foto (jpg, png, webp, gif), pdf o testo (txt, log, json, csv).")
    mime, ext = kind
    now = utcnow()
    rel_dir = Path(f"{now:%Y}") / f"{now:%m}"
    (settings.uploads_dir / rel_dir).mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    thumb_rel = None
    if mime.startswith("image/"):
        try:
            data, img = _clean_image(data)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise UploadRejected(415, "Immagine non leggibile.") from exc
        img.thumbnail((THUMB_PX, THUMB_PX))
        thumb_rel = rel_dir / f"{name}_thumb.webp"
        img.convert("RGB").save(settings.uploads_dir / thumb_rel, "WEBP", quality=80)
    rel = rel_dir / f"{name}{ext}"
    (settings.uploads_dir / rel).write_bytes(data)
    att = Attachment(
        entity_type=entity_type, entity_id=entity_id, filename=Path(upload.filename or f"file{ext}").name[:255],
        mime=mime, size=len(data), path=rel.as_posix(), thumb_path=thumb_rel.as_posix() if thumb_rel else None,
        operator_id=getattr(signer, "operator_id", None),
    )
    db.add(att)
    db.flush()
    return att


def remove_files(settings: Settings, att: Attachment) -> None:
    """Elimina i file di un allegato non ancora salvato (caricamento annullato)."""
    for rel in filter(None, [att.path, att.thumb_path]):
        (settings.uploads_dir / rel).unlink(missing_ok=True)


def trash_attachment(settings: Settings, db: Session, att: Attachment, signer) -> None:
    for rel in filter(None, [att.path, att.thumb_path]):
        src = settings.uploads_dir / rel
        if src.exists():
            dest = settings.uploads_dir / TRASH / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dest)
    att.deleted_at = utcnow()


def empty_trash(settings: Settings) -> int:
    folder = settings.uploads_dir / TRASH
    count = sum(1 for f in folder.rglob("*") if f.is_file()) if folder.exists() else 0
    if folder.exists():
        shutil.rmtree(folder)
    return count
