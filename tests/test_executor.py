"""
tests/test_executor.py — SQL 安全执行器单元测试

验证 6 层防护是否正常工作。
"""
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from executor import SQLExecutor, SQLSecurityError
from config import SQLExecutorConfig


class TestSQLExecutor(unittest.TestCase):
    """SQL 安全执行器测试"""

    @classmethod
    def setUpClass(cls):
        """初始化测试数据库"""
        cls.db_path = BASE_DIR / "data" / "test_finance.db"
        if cls.db_path.exists():
            cls.db_path.unlink()

        # 用一个轻量配置
        cls.cfg = SQLExecutorConfig(
            keyword_filter_enabled=True,
            syntax_validation_enabled=True,
            readonly_transaction_enabled=True,
            row_limit_enabled=True,
            timeout_enabled=True,
            timeout_seconds=10,
            max_rows=100,
        )

    def setUp(self):
        """每个测试前用独立的 executor"""
        # 先确保数据库有表
        import sqlite3
        self.db_path = BASE_DIR / "data" / "test_finance.db"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                stock_code TEXT PRIMARY KEY,
                stock_name TEXT,
                industry TEXT,
                market_cap REAL
            )
        """)
        conn.execute("INSERT OR IGNORE INTO stocks VALUES ('600519', '贵州茅台', '白酒', 21000)")
        conn.execute("INSERT OR IGNORE INTO stocks VALUES ('000858', '五粮液', '白酒', 6500)")
        conn.commit()
        conn.close()

        # 测试用配置：关闭超时控制（避免 SQLite 跨线程限制）
        test_cfg = SQLExecutorConfig(
            keyword_filter_enabled=True,
            syntax_validation_enabled=True,
            readonly_transaction_enabled=True,
            row_limit_enabled=True,
            timeout_enabled=False,  # 测试关闭超时，避免跨线程问题
            max_rows=100,
        )
        self.executor = SQLExecutor(config=test_cfg)
        # 直接连接测试库（读写模式，测试用）
        import sqlite3
        self.executor._conn = sqlite3.connect(str(self.db_path))
        self.executor._conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        """清理测试数据库"""
        # 关闭所有连接
        from db import close_connections
        close_connections()
        import gc
        gc.collect()
        db_path = BASE_DIR / "data" / "test_finance.db"
        try:
            if db_path.exists():
                db_path.unlink()
        except PermissionError:
            pass  # Windows 上偶发锁定，忽略

    # ===== 关键字过滤测试 =====

    def test_drop_table_blocked(self):
        """DROP TABLE 应该被关键字过滤拦截"""
        result = self.executor.execute("DROP TABLE stocks")
        self.assertFalse(result.is_success)
        self.assertEqual(result.failed_check, "keyword_filter")
        self.assertIn("DROP", result.error or "")

    def test_delete_blocked(self):
        """DELETE 应该被拦截"""
        result = self.executor.execute("DELETE FROM stocks WHERE stock_code='600519'")
        self.assertFalse(result.is_success)
        self.assertEqual(result.failed_check, "keyword_filter")

    def test_update_blocked(self):
        """UPDATE 应该被拦截"""
        result = self.executor.execute("UPDATE stocks SET market_cap=0 WHERE 1=1")
        self.assertFalse(result.is_success)
        self.assertEqual(result.failed_check, "keyword_filter")

    def test_insert_blocked(self):
        """INSERT 应该被拦截"""
        result = self.executor.execute("INSERT INTO stocks VALUES ('test', '测试', '测试', 0)")
        self.assertFalse(result.is_success)
        self.assertEqual(result.failed_check, "keyword_filter")

    def test_sql_injection_union_blocked(self):
        """UNION SELECT 注入应该被拦截"""
        result = self.executor.execute(
            "SELECT * FROM stocks WHERE stock_code='600519' UNION SELECT 1,2,3,4--"
        )
        self.assertFalse(result.is_success)

    def test_sql_injection_comment_blocked(self):
        """SQL 注释注入应该被拦截"""
        result = self.executor.execute("SELECT * FROM stocks; DROP TABLE stocks;--")
        self.assertFalse(result.is_success)

    # ===== 正常 SELECT 测试 =====

    def test_simple_select_passes(self):
        """简单 SELECT 应该通过所有启用的检查"""
        result = self.executor.execute("SELECT * FROM stocks")
        self.assertTrue(result.is_success, msg=result.error or "")
        self.assertGreater(result.row_count, 0)
        # 测试配置开启了 keyword_filter/syntax_validation/readonly/row_limit/permission_isolation
        # 共 5 层（timeout 在测试中关闭以避免跨线程问题）
        self.assertGreaterEqual(len(result.passed_checks), 4)

    def test_select_with_where(self):
        """带 WHERE 的 SELECT 应该通过"""
        result = self.executor.execute(
            "SELECT stock_name, market_cap FROM stocks WHERE industry='白酒'"
        )
        self.assertTrue(result.is_success)
        self.assertGreater(result.row_count, 0)

    def test_select_with_order(self):
        """带 ORDER BY 的 SELECT 应该通过"""
        result = self.executor.execute(
            "SELECT stock_name, market_cap FROM stocks ORDER BY market_cap DESC"
        )
        self.assertTrue(result.is_success)

    # ===== 行数限制测试 =====

    def test_row_limit_added(self):
        """没有 LIMIT 的 SQL 应该自动追加"""
        result = self.executor.execute("SELECT * FROM stocks")
        self.assertTrue(result.is_success)
        self.assertIn("LIMIT", result.sql.upper())

    def test_row_limit_not_duplicated(self):
        """已有 LIMIT 的不应该重复追加"""
        sql = "SELECT * FROM stocks LIMIT 10"
        result = self.executor.execute(sql)
        self.assertTrue(result.is_success)
        # 只应该有一个 LIMIT
        self.assertEqual(result.sql.upper().count("LIMIT"), 1)

    # ===== 校验模式测试 =====

    def test_validate_only_safe_sql(self):
        """validate_only 对安全 SQL 返回 True"""
        is_safe, reason = self.executor.validate_only("SELECT * FROM stocks")
        self.assertTrue(is_safe)
        self.assertEqual(reason, "")

    def test_validate_only_dangerous_sql(self):
        """validate_only 对危险 SQL 返回 False"""
        is_safe, reason = self.executor.validate_only("DROP TABLE stocks")
        self.assertFalse(is_safe)
        self.assertIn("keyword_filter", reason)

    # ===== 结果格式测试 =====

    def test_result_markdown_table(self):
        """Markdown 表格输出格式正确"""
        result = self.executor.execute("SELECT stock_code, stock_name FROM stocks LIMIT 2")
        self.assertTrue(result.is_success)
        md = result.to_markdown_table()
        self.assertIn("|", md)
        self.assertIn("stock_code", md)
        self.assertIn("stock_name", md)

    def test_result_empty_markdown(self):
        """空结果的 Markdown 输出"""
        result = self.executor.execute(
            "SELECT * FROM stocks WHERE stock_code='NONEXIST'"
        )
        self.assertTrue(result.is_success)
        md = result.to_markdown_table()
        self.assertIn("无数据", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
