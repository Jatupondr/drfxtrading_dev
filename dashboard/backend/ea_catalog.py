"""
ea_catalog.py — DRFX EA Catalog Backend Module
================================================
Vault สำหรับข้อมูล EA + Pricing Tiers ที่ index.html ดึงไปแสดง
+ endpoints สำหรับ admin panel แก้ไข

Storage: JSON files ที่ /data/catalog/ (configurable ผ่าน .env)
Auth:    reuse require_admin() จาก auth.py (cookie session)

ENV ที่รองรับ (.env):
    CATALOG_DATA_DIR=/absolute/path/to/data/catalog   (optional)
    CATALOG_KEEP_BACKUPS=10                            (optional)

Endpoints:
    Public (no auth):
        GET  /api/catalog/config    → { eas, pricing_tiers, updated_at }
        GET  /api/catalog/eas       → { count, eas }
        GET  /api/catalog/pricing   → { count, tiers }

    Admin (require_admin):
        POST   /api/catalog/eas          → save all EAs (bulk replace)
        POST   /api/catalog/pricing      → save all pricing tiers (bulk replace)
        GET    /api/catalog/backups      → list backup files
        POST   /api/catalog/restore/{filename} → restore from backup
"""

import os
import json
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from auth import require_admin

logger = logging.getLogger("catalog")

# ── Config ─────────────────────────────────────────────────
_default_dir = Path(__file__).resolve().parent.parent / "data" / "catalog"
DATA_DIR = Path(os.getenv("CATALOG_DATA_DIR", str(_default_dir)))
EAS_FILE = DATA_DIR / "eas.json"
PRICING_FILE = DATA_DIR / "pricing.json"
BACKUP_DIR = DATA_DIR / "backups"
KEEP_BACKUPS = int(os.getenv("CATALOG_KEEP_BACKUPS", "10"))

# Write lock — กัน race condition เวลาหลาย admin แก้พร้อมกัน
_write_lock = asyncio.Lock()


# ── File helpers ───────────────────────────────────────────
def _atomic_write_json(path: Path, data):
    """Write JSON atomically: temp file + rename (POSIX atomic)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _read_json(path: Path, default=None):
    """Read JSON safely, return default if missing/invalid"""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {path.name}: {e}")
        return default


def _backup(path: Path, label: str = ""):
    """Backup file before overwrite. Timestamped in backups/"""
    if not path.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    name = f"{path.stem}-{ts}{suffix}{path.suffix}"
    shutil.copy2(path, BACKUP_DIR / name)
    _cleanup_old_backups(path.stem)


def _cleanup_old_backups(prefix: str):
    """Keep only the latest KEEP_BACKUPS backups per file"""
    if not BACKUP_DIR.exists():
        return
    backups = sorted(BACKUP_DIR.glob(f"{prefix}-*"), reverse=True)
    for old in backups[KEEP_BACKUPS:]:
        try:
            old.unlink()
        except Exception as e:
            logger.warning(f"Cleanup backup {old.name} failed: {e}")


def _get_last_modified() -> str:
    """ISO timestamp ของไฟล์ล่าสุด"""
    times = []
    for f in [EAS_FILE, PRICING_FILE]:
        if f.exists():
            times.append(f.stat().st_mtime)
    if not times:
        return ""
    return datetime.fromtimestamp(max(times), tz=timezone.utc).isoformat()


# ── Init ───────────────────────────────────────────────────
def init_catalog():
    """เรียกใน lifespan startup — สร้าง data dir ถ้ายังไม่มี"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    eas_exists = EAS_FILE.exists()
    pricing_exists = PRICING_FILE.exists()
    logger.info(
        f"Catalog data dir: {DATA_DIR} "
        f"(eas.json: {'ok' if eas_exists else 'missing'}, "
        f"pricing.json: {'ok' if pricing_exists else 'missing'})"
    )


# ── Router ─────────────────────────────────────────────────
catalog_router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class BulkEAsBody(BaseModel):
    """Body สำหรับ save-all EAs — accept any dict fields for flexibility"""
    eas: list[dict]


class BulkPricingBody(BaseModel):
    """Body สำหรับ save-all Pricing Tiers"""
    tiers: list[dict]


# ── Public endpoints ──────────────────────────────────────
@catalog_router.get("/config")
async def get_config():
    """ดึงข้อมูลทั้งหมดในการเรียกเดียว (ใช้ใน index.html catalog site)"""
    return {
        "eas": _read_json(EAS_FILE, default=[]),
        "pricing_tiers": _read_json(PRICING_FILE, default=[]),
        "updated_at": _get_last_modified(),
    }


@catalog_router.get("/eas")
async def get_eas():
    """ดึง EAs อย่างเดียว"""
    eas = _read_json(EAS_FILE, default=[])
    return {"count": len(eas), "eas": eas}


@catalog_router.get("/pricing")
async def get_pricing():
    """ดึง Pricing Tiers อย่างเดียว"""
    tiers = _read_json(PRICING_FILE, default=[])
    return {"count": len(tiers), "tiers": tiers}


# ── Admin endpoints ────────────────────────────────────────
@catalog_router.post("/eas")
async def save_all_eas(body: BulkEAsBody, request: Request):
    """Bulk replace ทั้ง list ของ EAs"""
    require_admin(request)

    # ป้องกัน accidental wipe: ต้องมีอย่างน้อย 1 EA
    if not body.eas:
        raise HTTPException(400, "Cannot save empty EAs list. Use bulk delete API if intentional.")

    # ต้องมี name (unique) ทุก EA
    names = [e.get("name") for e in body.eas]
    if any(not n for n in names):
        raise HTTPException(400, "All EAs must have 'name' field")
    if len(set(names)) != len(names):
        raise HTTPException(400, "Duplicate EA names found")

    async with _write_lock:
        _backup(EAS_FILE, "save-all")
        _atomic_write_json(EAS_FILE, body.eas)

    logger.info(f"Catalog: saved {len(body.eas)} EAs")
    return {"ok": True, "count": len(body.eas), "updated_at": _get_last_modified()}


@catalog_router.post("/pricing")
async def save_pricing(body: BulkPricingBody, request: Request):
    """Bulk replace pricing tiers"""
    require_admin(request)

    if not body.tiers:
        raise HTTPException(400, "Cannot save empty pricing tiers list")

    async with _write_lock:
        _backup(PRICING_FILE, "save-all")
        _atomic_write_json(PRICING_FILE, body.tiers)

    logger.info(f"Catalog: saved {len(body.tiers)} pricing tiers")
    return {"ok": True, "count": len(body.tiers), "updated_at": _get_last_modified()}


@catalog_router.get("/backups")
async def list_backups(request: Request):
    """List backup files ทั้งหมด"""
    require_admin(request)
    if not BACKUP_DIR.exists():
        return {"backups": []}
    items = []
    for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if not f.is_file():
            continue
        stat = f.stat()
        items.append({
            "name": f.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "target": "eas.json" if f.name.startswith("eas-") else (
                      "pricing.json" if f.name.startswith("pricing-") else "?"),
        })
    return {"backups": items}


@catalog_router.post("/restore/{backup_name}")
async def restore_backup(backup_name: str, request: Request):
    """Restore ไฟล์จาก backup (จะ backup ตัวปัจจุบันก่อน)"""
    require_admin(request)

    # ป้องกัน path traversal
    if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise HTTPException(400, "Invalid backup name")

    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists() or not backup_path.is_file():
        raise HTTPException(404, "Backup not found")

    # หาปลายทางจาก prefix
    if backup_name.startswith("eas-"):
        target = EAS_FILE
    elif backup_name.startswith("pricing-"):
        target = PRICING_FILE
    else:
        raise HTTPException(400, "Unknown backup type")

    async with _write_lock:
        _backup(target, "before-restore")
        shutil.copy2(backup_path, target)

    logger.info(f"Catalog: restored {target.name} from {backup_name}")
    return {"ok": True, "restored_from": backup_name, "target": target.name}
