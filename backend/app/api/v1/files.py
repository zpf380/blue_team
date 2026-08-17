"""文件上传 API：MinIO 对象存储 + FileRecord（预签名 URL 供浏览器访问）。"""
import asyncio
import datetime as dt
import io
import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.exceptions import AppError, ERR_INTERNAL, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import FileRecord, User

router = APIRouter(tags=["文件"])

# 上传白名单：扩展名（硬门槛）+ 期望 MIME 前缀（软校验，防"改扩展名的脚本/可执行文件"）
_UPLOAD_ALLOWED_EXTS = {e for e in settings.UPLOAD_ALLOWED_EXTENSIONS.split(",") if e}
_EXT_MIME_HINT = {
    "png": "image/", "jpg": "image/", "jpeg": "image/", "gif": "image/", "webp": "image/", "bmp": "image/", "ico": "image/",
    "pdf": "application/pdf",
    "doc": "application/msword", "docx": "officedocument",
    "xls": "application/vnd.ms-excel", "xlsx": "officedocument",
    "ppt": "application/vnd.ms-powerpoint", "pptx": "officedocument",
    "csv": "text/", "txt": "text/", "md": "text/", "log": "text/",
    "zip": "application/zip", "rar": "x-rar", "7z": "x-7z", "tar": "x-tar", "gz": "x-gzip",
}


def _client():
    from minio import Minio

    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


@router.post("/files")
async def upload_file(
    file: UploadFile,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _UPLOAD_ALLOWED_EXTS:
        allowed = "、".join(sorted(_UPLOAD_ALLOWED_EXTS))
        raise AppError(code=ERR_VALIDATION, message=f"不支持的文件类型 .{ext or '(无扩展名)'}（仅允许：{allowed}）")
    data = await file.read()
    if len(data) > settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024:
        raise AppError(code=ERR_VALIDATION, message=f"文件超过 {settings.UPLOAD_MAX_SIZE_MB}MB 限制")
    # MIME 软校验：扩展名白名单内的文件，Content-Type 明显不匹配也拒绝（改扩展名的可执行脚本）
    mime = (file.content_type or "").lower()
    if mime and mime != "application/octet-stream":
        hint = _EXT_MIME_HINT.get(ext, "")
        if hint and hint not in mime:
            raise AppError(code=ERR_VALIDATION, message=f"文件内容类型 {mime} 与扩展名 .{ext} 不匹配，已拒绝")
    try:
        client = _client()
        if not client.bucket_exists(settings.MINIO_BUCKET):
            client.make_bucket(settings.MINIO_BUCKET)
        ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
        object_key = f"chat/{user.id}/{uuid.uuid4().hex}{ext}"
        await asyncio.to_thread(
            client.put_object,
            settings.MINIO_BUCKET, object_key, io.BytesIO(data), len(data), content_type=file.content_type or "application/octet-stream",
        )
        url = client.presigned_get_object(settings.MINIO_BUCKET, object_key, expires=dt.timedelta(days=7))
    except Exception as exc:  # MinIO 不可达等
        raise AppError(code=ERR_INTERNAL, message=f"文件上传失败（存储服务不可用）：{type(exc).__name__}")

    session.add(FileRecord(user_id=user.id, filename=filename, object_key=object_key, url=url, size=len(data), mime_type=file.content_type))
    await session.commit()
    return ok_response(data={"url": url, "filename": filename, "size": len(data)})
