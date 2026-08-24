"""审计中心接口：操作日志查询 / 导出 / 合规报告（仅 admin / auditor）。"""
import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_user_agent, require_role
from app.core.exceptions import AppError, ERR_NOT_FOUND, ERR_VALIDATION, ok_response
from app.db.session import get_db
from app.models import AuditReport, OperationLog, User
from app.schemas.audit import ReportCreate
from app.schemas.common import Page
from app.services.audit_log import record
from app.services.audit_report import compute_audit_stats, generate_report

router = APIRouter(prefix="/audit", tags=["审计中心"])


@router.get("/logs")
async def list_logs(
    request: Request,
    keyword: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "auditor"])),
):
    query = select(OperationLog)
    if action:
        query = query.where(OperationLog.action == action)
    if keyword:
        query = query.where(OperationLog.username.ilike(f"%{keyword}%"))
    if date_from or date_to:
        # 接受 "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM:SS"
        fmt = "%Y-%m-%d"
        if date_from and len(date_from) > 10:
            fmt = "%Y-%m-%d %H:%M:%S"
        try:
            start = dt.datetime.strptime(date_from, fmt).astimezone(dt.timezone.utc) if date_from else None
            end = dt.datetime.strptime(date_to, fmt).astimezone(dt.timezone.utc) if date_to else None
        except ValueError:
            raise AppError(code=ERR_VALIDATION, message="日期格式应为 YYYY-MM-DD")
        if start:
            query = query.where(OperationLog.created_at >= start)
        if end:
            query = query.where(OperationLog.created_at <= end + dt.timedelta(days=1) - dt.timedelta(seconds=1))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(query.order_by(OperationLog.id.desc()).offset((page - 1) * size).limit(size))
    ).scalars().all()
    await record(session, current, "audit:log:view", ip_address=await get_client_ip(request))
    await session.commit()
    return ok_response(
        data=Page(
            items=[
                {
                    "id": r.id,
                    "username": r.username,
                    "role_code": r.role_code,
                    "action": r.action,
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "detail": r.detail,
                    "ip_address": str(r.ip_address) if r.ip_address else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
            total=total,
            page=page,
            size=size,
        )
    )


@router.get("/logs/export")
async def export_logs(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "auditor"])),
):
    rows = (await session.execute(select(OperationLog).order_by(OperationLog.id.desc()).limit(5000))).scalars().all()
    await record(
        session, current, "audit:log:export", detail={"count": len(rows)},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "username", "role", "action", "target_type", "target_id", "ip", "created_at"])
    for r in rows:
        writer.writerow([r.id, r.username, r.role_code, r.action, r.target_type, r.target_id, r.ip_address, r.created_at])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


# ---------- 合规审计报告 ----------
@router.get("/reports/stats")
async def audit_stats(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["admin", "auditor"])),
):
    """实时合规统计（不落库），默认近 14 天。"""
    stats = await compute_audit_stats(session, date_from, date_to)
    return ok_response(data=stats)


@router.post("/reports")
async def create_audit_report(
    data: ReportCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(require_role(["admin", "auditor"])),
):
    """生成并保存一份合规审计报告快照。"""
    report = await generate_report(session, current, data.report_type, data.date_from, data.date_to)
    await session.flush()
    await record(
        session, current, "audit:report:generate", target_type="audit_report", target_id=str(report.id),
        detail={"report_type": report.report_type, "title": report.title},
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(data={"id": report.id, "title": report.title})


@router.get("/reports")
async def list_audit_reports(
    report_type: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["admin", "auditor"])),
):
    query = select(AuditReport)
    if report_type:
        query = query.where(AuditReport.report_type == report_type)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await session.execute(query.order_by(AuditReport.id.desc()).offset((page - 1) * size).limit(size))
    ).scalars().all()
    return ok_response(data=Page(items=[
        {
            "id": r.id, "report_type": r.report_type, "title": r.title,
            "date_from": r.date_from.isoformat() if r.date_from else None,
            "date_to": r.date_to.isoformat() if r.date_to else None,
            "summary": r.summary, "generated_by_name": r.generated_by_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ], total=total, page=page, size=size))


@router.get("/reports/{report_id}")
async def get_audit_report(
    report_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["admin", "auditor"])),
):
    r = await session.get(AuditReport, report_id)
    if not r:
        raise AppError(code=ERR_NOT_FOUND, message="报告不存在")
    return ok_response(data={
        "id": r.id, "report_type": r.report_type, "title": r.title,
        "date_from": r.date_from.isoformat() if r.date_from else None,
        "date_to": r.date_to.isoformat() if r.date_to else None,
        "summary": r.summary, "report_data": r.report_data,
        "generated_by_name": r.generated_by_name, "created_at": r.created_at.isoformat() if r.created_at else None,
    })


@router.get("/reports/{report_id}/export")
async def export_audit_report(
    report_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["admin", "auditor"])),
):
    """将报告快照导出为 CSV。"""
    r = await session.get(AuditReport, report_id)
    if not r:
        raise AppError(code=ERR_NOT_FOUND, message="报告不存在")
    data = r.report_data or {}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["统计周期", data.get("date_from"), "~", data.get("date_to")])
    writer.writerow(["总操作数", data.get("total_ops", 0)])
    writer.writerow(["活跃用户", data.get("active_users", 0)])
    writer.writerow(["敏感操作", data.get("sensitive_ops", 0)])
    writer.writerow(["登录次数", data.get("logins", 0)])
    writer.writerow([])
    writer.writerow(["操作类型", "次数"])
    for a in data.get("actions", []):
        writer.writerow([a["action"], a["count"]])
    writer.writerow([])
    writer.writerow(["用户名", "角色", "次数"])
    for u in data.get("users", []):
        writer.writerow([u["username"], u["role_code"], u["count"]])
    writer.writerow([])
    writer.writerow(["敏感操作明细"])
    writer.writerow(["ID", "操作人", "动作", "对象类型", "对象ID", "IP", "时间"])
    for s in data.get("sensitive", []):
        writer.writerow([s["id"], s["username"], s["action"], s["target_type"], s["target_id"], s["ip_address"], s["created_at"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_report_{r.id}.csv"},
    )
