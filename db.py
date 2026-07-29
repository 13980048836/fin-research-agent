"""
db.py — 数据库连接管理

SQLite 只读模式 + 连接池 + 线程安全封装。
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import get_config

_local = threading.local()


def _get_connection(read_only: bool = None) -> sqlite3.Connection:
    """获取当前线程的数据库连接（懒加载）"""
    cfg = get_config().database
    if read_only is None:
        read_only = cfg.read_only

    key = "ro" if read_only else "rw"
    conn = getattr(_local, f"conn_{key}", None)

    if conn is None:
        db_path = Path(cfg.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        uri = f"file:{db_path}"
        if read_only:
            uri += "?mode=ro"

        conn = sqlite3.connect(
            uri,
            timeout=cfg.timeout,
            uri=True,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        if not read_only:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA foreign_keys=ON")
        else:
            try:
                conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.OperationalError:
                pass

        setattr(_local, f"conn_{key}", conn)

    return conn


@contextmanager
def get_db(read_only: bool = None) -> Iterator[sqlite3.Connection]:
    """
    上下文管理器：获取数据库连接。

    用法:
        with get_db() as conn:
            rows = conn.execute("SELECT 1").fetchall()

    Args:
        read_only: 是否只读模式，None 则使用配置默认值
    """
    conn = _get_connection(read_only)
    try:
        yield conn
        if not (read_only if read_only is not None else get_config().database.read_only):
            conn.commit()
    except Exception:
        if not (read_only if read_only is not None else get_config().database.read_only):
            conn.rollback()
        raise


def get_readonly_db() -> sqlite3.Connection:
    """直接获取只读连接（用于需要传连接对象的场景）"""
    return _get_connection(read_only=True)


def close_connections() -> None:
    """关闭当前线程所有连接"""
    for key in ("conn_ro", "conn_rw"):
        conn = getattr(_local, key, None)
        if conn is not None:
            conn.close()
            setattr(_local, key, None)


def get_schema_info() -> list[dict]:
    """获取数据库所有表的 schema 信息"""
    with get_db(read_only=True) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        schema = []
        for table in tables:
            table_name = table["name"]
            columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            schema.append({
                "table_name": table_name,
                "columns": [
                    {
                        "name": col["name"],
                        "type": col["type"],
                        "nullable": not col["notnull"],
                        "pk": bool(col["pk"]),
                    }
                    for col in columns
                ],
            })
        return schema
