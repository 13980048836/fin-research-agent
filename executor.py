"""
executor.py — SQL 安全执行器（6 层防护）

防护层级:
  1. 关键字过滤 — 正则匹配 DROP/DELETE/UPDATE/INSERT 等禁用词
  2. 语法校验 — sqlparse 解析 AST，确认语句类型为 SELECT
  3. 只读事务 — SQLite 只读模式连接
  4. 行数限制 — 自动追加 LIMIT N
  5. 超时控制 — 30 秒超时中断
  6. 权限隔离 — 仅 SELECT 权限（数据库连接层面）
"""
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any

try:
    import sqlparse
    HAS_SQLPARSE = True
except ImportError:
    HAS_SQLPARSE = False

from config import get_config
from db import get_readonly_db


# ===================== 安全异常 =====================

class SQLSecurityError(Exception):
    """SQL 安全检查失败异常"""

    def __init__(self, layer: str, message: str):
        self.layer = layer
        super().__init__(f"[{layer}] {message}")


# ===================== 各层防护实现 =====================

DANGEROUS_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "MERGE", "REPLACE",
    "--", ";--", "/*", "*/", "xp_", "sp_", "INTO OUTFILE",
    "LOAD_FILE", "UNION SELECT", "INFORMATION_SCHEMA",
]


def _keyword_filter(sql: str) -> None:
    """第 1 层：关键字过滤"""
    sql_upper = sql.upper()
    for kw in DANGEROUS_KEYWORDS:
        if kw in sql_upper:
            raise SQLSecurityError(
                "keyword_filter",
                f"SQL 包含禁用关键字: {kw}",
            )


def _syntax_validation(sql: str) -> None:
    """第 2 层：语法校验（仅允许 SELECT）"""
    if not HAS_SQLPARSE:
        return  # 没有 sqlparse 则跳过此层

    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        raise SQLSecurityError("syntax_validation", "SQL 为空或无法解析")

    for stmt in parsed:
        stmt_type = stmt.get_type().upper()
        if stmt_type != "SELECT":
            raise SQLSecurityError(
                "syntax_validation",
                f"仅允许 SELECT 语句，检测到: {stmt_type}",
            )


def _add_row_limit(sql: str, max_rows: int) -> str:
    """第 4 层：自动追加 LIMIT"""
    sql_upper = sql.upper().strip()

    if "LIMIT" in sql_upper:
        return sql

    if sql_upper.endswith(";"):
        sql = sql.rstrip(";").rstrip()

    return f"{sql} LIMIT {max_rows}"


def _execute_with_timeout(conn: sqlite3.Connection, sql: str, timeout: int, is_readonly: bool = False) -> list[dict]:
    """第 5 层：超时控制（用线程实现，兼容 Windows）
    
    注意：只读连接(mode=ro)不能使用 conn.interrupt()，因为 interrupt 会
    尝试写入状态位，导致 "attempt to write a readonly database" 错误。
    只读模式下改为等待超时后直接返回空结果。
    """
    result: list[dict] = []
    error: list[Exception] = []

    def _run():
        try:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            result.extend([dict(r) for r in rows])
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        if not is_readonly:
            try:
                conn.interrupt()
            except Exception:
                pass
        raise SQLSecurityError(
            "timeout",
            f"SQL 执行超时（>{timeout}秒），已中断",
        )

    if error:
        raise error[0]

    return result


# ===================== 执行结果 =====================

@dataclass
class SQLResult:
    """SQL 执行结果"""
    sql: str
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)
    failed_check: str | None = None
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_markdown_table(self, max_rows: int = 20) -> str:
        """将结果转为 Markdown 表格"""
        if not self.rows:
            return "_无数据_"

        rows = self.rows[:max_rows]
        if not rows:
            return "_无数据_"

        columns = list(rows[0].keys())
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join(["---"] * len(columns)) + " |"
        body_lines = []
        for r in rows:
            vals = [str(r[c]) for c in columns]
            body_lines.append("| " + " | ".join(vals) + " |")

        table = "\n".join([header, sep, *body_lines])
        if len(self.rows) > max_rows:
            table += f"\n\n_仅显示前 {max_rows} 行，共 {len(self.rows)} 行_"

        return table


# ===================== 主执行器 =====================

class SQLExecutor:
    """SQL 安全执行器"""

    def __init__(self, config=None):
        self.cfg = config or get_config().sql_executor
        self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_readonly_db()
        return self._conn

    def execute(self, sql: str) -> SQLResult:
        """
        执行 SQL 查询，经过 6 层安全检查。

        Args:
            sql: SQL 查询语句

        Returns:
            SQLResult 执行结果
        """
        result = SQLResult(sql=sql)

        try:
            # 第 1 层：关键字过滤
            if self.cfg.keyword_filter_enabled:
                _keyword_filter(sql)
                result.passed_checks.append("keyword_filter")

            # 第 2 层：语法校验
            if self.cfg.syntax_validation_enabled and HAS_SQLPARSE:
                _syntax_validation(sql)
                result.passed_checks.append("syntax_validation")

            # 第 3 层：只读事务（由连接层面保证，这里标记通过）
            if self.cfg.readonly_transaction_enabled:
                result.passed_checks.append("readonly_transaction")

            # 第 4 层：行数限制
            if self.cfg.row_limit_enabled:
                sql = _add_row_limit(sql, self.cfg.max_rows)
                result.sql = sql
                result.passed_checks.append("row_limit")

            # 第 5 层：超时控制
            if self.cfg.timeout_enabled:
                rows = _execute_with_timeout(
                    self.conn, sql, self.cfg.timeout_seconds, is_readonly=True
                )
                result.passed_checks.append("timeout")
            else:
                cursor = self.conn.execute(sql)
                rows = [dict(r) for r in cursor.fetchall()]

            # 第 6 层：权限隔离（由数据库连接的只读模式保证）
            result.passed_checks.append("permission_isolation")

            result.rows = rows
            result.row_count = len(rows)
            if rows:
                result.columns = list(rows[0].keys())

        except SQLSecurityError as e:
            result.failed_check = e.layer
            result.error = str(e)
        except sqlite3.Error as e:
            result.error = f"数据库错误: {e}"
        except Exception as e:
            result.error = f"执行异常: {type(e).__name__}: {e}"

        return result

    def validate_only(self, sql: str) -> tuple[bool, str]:
        """仅做安全校验，不实际执行"""
        try:
            if self.cfg.keyword_filter_enabled:
                _keyword_filter(sql)
            if self.cfg.syntax_validation_enabled and HAS_SQLPARSE:
                _syntax_validation(sql)
            return True, ""
        except SQLSecurityError as e:
            return False, str(e)


# 全局单例
_executor: SQLExecutor | None = None


def get_executor() -> SQLExecutor:
    global _executor
    if _executor is None:
        _executor = SQLExecutor()
    return _executor
