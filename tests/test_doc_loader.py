"""
tests/test_doc_loader.py — 文档加载与切分测试
"""
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from doc_loader import DocumentLoader
from config import AppConfig, SplitterConfig


class TestDocumentLoader(unittest.TestCase):
    """文档加载器测试"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        # 用临时配置
        self.cfg = AppConfig()
        self.cfg.docs_dir = self.temp_dir
        self.loader = DocumentLoader(config=self.cfg)

    def tearDown(self):
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def _write_test_file(self, name: str, content: str, subdir: str = ""):
        """写测试文件"""
        fpath = self.temp_dir / subdir / name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        return fpath

    def test_load_txt_file(self):
        """加载 TXT 文件"""
        content = "这是测试文本。\n" * 100
        fpath = self._write_test_file("test.txt", content)

        docs = self.loader.load_file(fpath)
        self.assertGreater(len(docs), 0)
        # 内容应该被切分
        self.assertLess(len(docs[0].page_content), len(content) + 100)

    def test_load_markdown_file(self):
        """加载 Markdown 文件"""
        content = """# 标题一

这是第一段内容。

## 标题二

这是第二段内容。

### 子标题

这是子标题内容。
"""
        fpath = self._write_test_file("test.md", content)
        docs = self.loader.load_file(fpath)
        self.assertGreater(len(docs), 0)

    def test_load_directory(self):
        """加载整个目录"""
        for i in range(3):
            self._write_test_file(
                f"doc_{i}.txt",
                f"这是第 {i} 份文档的内容。\n" * 20,
                subdir="subdir",
            )

        result = self.loader.load_directory(self.temp_dir)
        self.assertEqual(result.total_files, 3)
        self.assertGreaterEqual(result.total_chunks, 3)
        self.assertEqual(len(result.failed_files), 0)

    def test_unsupported_format(self):
        """不支持的格式应该报错"""
        fpath = self._write_test_file("test.docx", "测试")
        with self.assertRaises(ValueError):
            self.loader.load_file(fpath)

    def test_empty_directory(self):
        """空目录返回空结果"""
        result = self.loader.load_directory(self.temp_dir)
        self.assertEqual(result.total_files, 0)
        self.assertEqual(result.total_chunks, 0)

    def test_chunk_size_config(self):
        """不同 chunk_size 配置产生不同数量的片段"""
        content = "这是一段测试文本。" * 200
        fpath = self._write_test_file("long.txt", content)

        # 小 chunk
        small_cfg = AppConfig()
        small_cfg.splitter = SplitterConfig(chunk_size=100, chunk_overlap=20)
        small_loader = DocumentLoader(config=small_cfg)
        small_docs = small_loader.load_file(fpath)

        # 大 chunk
        big_cfg = AppConfig()
        big_cfg.splitter = SplitterConfig(chunk_size=500, chunk_overlap=50)
        big_loader = DocumentLoader(config=big_cfg)
        big_docs = big_loader.load_file(fpath)

        # 小 chunk 应该切更多片
        self.assertGreater(len(small_docs), len(big_docs))

    def test_compare_split_strategies(self):
        """切分策略对比功能"""
        content = "# 标题\n\n" + "段落内容。" * 100
        fpath = self._write_test_file("compare.md", content)

        results = self.loader.compare_split_strategies(fpath)
        # 至少应该有 recursive 和 character 两种
        self.assertGreaterEqual(len(results), 2)
        self.assertIn("recursive", results)
        self.assertIn("character", results)

        for strategy, info in results.items():
            self.assertIn("chunks", info)
            self.assertIn("avg_size", info)
            self.assertGreater(info["chunks"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
