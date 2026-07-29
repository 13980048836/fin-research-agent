"""
pdf_processor.py — 智能 PDF 处理器

根据 PDF 类型自动路由到三种处理路径：
  1. 原生 PDF（文本版）   → PyMuPDF 直接抽取文本
  2. 扫描件 PDF（图片型） → OCR 识别（PaddleOCR 优先，降级到视觉模型）
  3. 图表/复杂表格        → 多模态视觉理解（DashScope qwen-vl-max）

自动检测策略（按页）：
  - 检测到表格结构           → 视觉理解
  - 文本字符数 < 阈值 且有图片 → OCR 扫描件
  - 文本充足                → 原生抽取

使用:
  from pdf_processor import PDFProcessor
  processor = PDFProcessor()
  pages = processor.process("report.pdf")
  for p in pages:
      print(p.page_type, p.text[:80])
"""
import io
import os
import base64
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal, Optional

from config import get_config

logger = logging.getLogger(__name__)

# ── 依赖探测 ──────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from paddleocr import PaddleOCR
    HAS_PADDLE_OCR = True
except ImportError:
    HAS_PADDLE_OCR = False

try:
    import dashscope
    from dashscope import MultiModalConversation
    HAS_DASHSCOPE = True
except ImportError:
    HAS_DASHSCOPE = False


PageType = Literal["native", "scanned", "vision"]


@dataclass
class PDFPage:
    """单页 PDF 的处理结果"""
    index: int                       # 页码（从 1 开始）
    page_type: PageType              # 处理路径
    text: str = ""                   # 提取的文本
    image_bytes: Optional[bytes] = None  # 渲染的页面图片（PNG）
    tables: list = field(default_factory=list)  # 检测到的表格
    source: str = ""                 # 来源文件


@dataclass
class PDFProcessResult:
    """整个 PDF 的处理结果"""
    pages: list = field(default_factory=list)
    total_pages: int = 0
    native_pages: int = 0
    scanned_pages: int = 0
    vision_pages: int = 0
    failed: bool = False
    error: str = ""


class PDFProcessor:
    """智能 PDF 处理器：按页面类型自动路由"""

    def __init__(self, config=None):
        self.cfg = config or get_config().pdf
        self._ocr_engine = None
        self._dashscope_configured = bool(os.getenv("DASHSCOPE_API_KEY"))

    # ── 主入口 ───────────────────────────────────────────
    def process(self, file_path) -> PDFProcessResult:
        """处理整个 PDF 文件，自动路由每页"""
        file_path = Path(file_path)
        result = PDFProcessResult()

        if not HAS_FITZ:
            # 降级到 pypdf
            return self._fallback_pypdf(file_path)

        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            logger.error("打开 PDF 失败 %s: %s", file_path, e)
            result.failed = True
            result.error = str(e)
            return result

        result.total_pages = len(doc)
        logger.info("📄 处理 PDF: %s (%d 页)", file_path.name, result.total_pages)

        for i, page in enumerate(doc):
            page_result = self._process_page(page, i + 1, str(file_path))
            result.pages.append(page_result)

            if page_result.page_type == "native":
                result.native_pages += 1
            elif page_result.page_type == "scanned":
                result.scanned_pages += 1
            else:
                result.vision_pages += 1

        doc.close()

        logger.info(
            "✅ PDF 处理完成: 原生=%d, 扫描=%d, 视觉=%d",
            result.native_pages, result.scanned_pages, result.vision_pages,
        )
        return result

    def process_to_text(self, file_path) -> str:
        """处理 PDF 并合并为纯文本（供 DocumentLoader 使用）"""
        result = self.process(file_path)
        if result.failed:
            return ""

        parts = []
        for page in result.pages:
            if page.text.strip():
                parts.append(f"--- 第 {page.index} 页 ---\n{page.text}")
        return "\n\n".join(parts)

    # ── 单页处理 ─────────────────────────────────────────
    def _process_page(self, page, index: int, source: str) -> PDFPage:
        """处理单页：分类 → 路由"""
        # 1. 抽取原生文本
        raw_text = page.get_text("text") or ""
        raw_text = raw_text.strip()

        # 2. 检测表格
        tables = self._detect_tables(page)

        # 3. 分类
        page_type = self._classify_page(page, raw_text, tables)

        # 4. 路由到对应处理路径
        pdf_page = PDFPage(
            index=index,
            page_type=page_type,
            text=raw_text,
            tables=tables,
            source=source,
        )

        if page_type == "native":
            # 原生：直接用抽取的文本
            pdf_page.text = self._clean_native_text(raw_text)

        elif page_type == "scanned":
            # 扫描件：OCR
            image_bytes = self._render_page(page)
            pdf_page.image_bytes = image_bytes
            pdf_page.text = self._ocr(image_bytes)

        elif page_type == "vision":
            # 图表/表格：多模态视觉理解
            image_bytes = self._render_page(page)
            pdf_page.image_bytes = image_bytes
            # 构造表格提示（不传 PyMuPDF 对象，避免序列化问题）
            hint = (
                f"此页检测到 {len(tables)} 个表格结构。"
                "请识别并提取页面中的所有文字、表格数据和图表信息，"
                "保持原有的结构和逻辑关系。表格请用 Markdown 格式输出。"
                if tables else ""
            )
            pdf_page.text = self._vision_understand(image_bytes, hint=hint)

        return pdf_page

    # ── 页面分类 ─────────────────────────────────────────
    def _classify_page(self, page, text: str, tables: list) -> PageType:
        """
        自动判断页面类型

        优先级:
          1. 有表格结构 + 启用视觉 → vision
          2. 文本 < 阈值 + 有图片  → scanned
          3. 其他                  → native
        """
        text_len = len(text)

        # 检测到表格 → 视觉理解（表格用文本抽取容易打散）
        if tables and self.cfg.vision_for_tables:
            return "vision"

        # 文本不足，可能是扫描件
        if text_len < self.cfg.text_threshold:
            images = page.get_images(full=True)
            if images:
                return "scanned"
            # 没图片也没文字，可能是空白页或特殊页
            if text_len == 0:
                return "scanned"

        return "native"

    def _detect_tables(self, page) -> list:
        """检测页面中的表格"""
        try:
            if hasattr(page, "find_tables"):
                tabs = page.find_tables()
                return list(tabs.tables) if tabs.tables else []
        except Exception:
            pass
        return []

    # ── 路径 1: 原生文本抽取 ─────────────────────────────
    def _clean_native_text(self, text: str) -> str:
        """清理原生抽取的文本"""
        if not text:
            return ""
        # 去除多余空白行
        lines = [ln.rstrip() for ln in text.split("\n")]
        return "\n".join(lines).strip()

    # ── 路径 2: OCR 识别 ────────────────────────────────
    def _ocr(self, image_bytes: bytes) -> str:
        """
        OCR 识别扫描件

        优先级: PaddleOCR（本地，快） → 视觉模型（云端，准）
        """
        if not image_bytes:
            return ""

        # 优先 PaddleOCR
        if HAS_PADDLE_OCR and self.cfg.ocr_backend == "paddleocr":
            try:
                return self._paddle_ocr(image_bytes)
            except Exception as e:
                logger.warning("PaddleOCR 失败，降级到视觉模型: %s", e)

        # 降级到视觉模型做 OCR
        if self._dashscope_configured:
            return self._vision_understand(
                image_bytes, hint="这是一份扫描件，请识别图片中的所有文字内容，保持原有结构和格式。"
            )

        logger.warning("无可用 OCR 后端（paddleocr 未安装且未配置 DashScope）")
        return ""

    def _paddle_ocr(self, image_bytes: bytes) -> str:
        """PaddleOCR 识别"""
        if self._ocr_engine is None:
            self._ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang="ch",
                show_log=False,
            )

        # PaddleOCR 接受文件路径或 numpy 数组，这里用 PIL 转 numpy
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)

        result = self._ocr_engine.ocr(img_array, cls=True)
        if not result or not result[0]:
            return ""

        lines = []
        for line in result[0]:
            text = line[1][0]
            lines.append(text)
        return "\n".join(lines)

    # ── 路径 3: 多模态视觉理解 ──────────────────────────
    def _vision_understand(self, image_bytes: bytes, hint: str = "") -> str:
        """
        使用 DashScope qwen-vl-max 进行视觉理解

        适用于: 图表、复杂表格、含图形的页面
        """
        if not HAS_DASHSCOPE or not self._dashscope_configured:
            logger.warning("DashScope 未配置，跳过视觉理解")
            return ""

        if not image_bytes:
            return ""

        # 构造默认提示词
        if not hint:
            hint = (
                "这是一份金融研报/财报页面，可能包含表格、图表或图文混排内容。"
                "请仔细识别并提取页面中的所有文字、表格数据和图表信息，"
                "保持原有的结构和逻辑关系，用清晰的格式输出。"
                "对于表格，请用 Markdown 表格格式输出。"
            )

        # 写入临时文件（dashscope 传文件路径比 base64 更稳定）
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, dir=tempfile.gettempdir()
            ) as f:
                f.write(image_bytes)
                tmp_path = f.name

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"image": f"file://{tmp_path}"},
                        {"text": hint},
                    ],
                }
            ]

            response = MultiModalConversation.call(
                model=self.cfg.vl_model,
                messages=messages,
                api_key=os.getenv("DASHSCOPE_API_KEY"),
            )

            if response.status_code == 200:
                output = response.output
                if output and output.choices:
                    content = output.choices[0].message.content
                    if isinstance(content, list):
                        return " ".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in content
                        )
                    return str(content)
            else:
                logger.error("视觉理解失败: %s (code=%s)", response.message, response.code)
                return ""
        except Exception as e:
            logger.error("视觉理解异常: %s", e)
            return ""
        finally:
            # 清理临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return ""

    # ── 页面渲染 ─────────────────────────────────────────
    def _render_page(self, page, dpi: int = None) -> bytes:
        """将 PDF 页面渲染为 PNG 图片（给 OCR/视觉模型用）"""
        dpi = dpi or self.cfg.render_dpi
        try:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png")
        except Exception as e:
            logger.error("页面渲染失败: %s", e)
            return b""

    # ── 降级方案 ─────────────────────────────────────────
    def _fallback_pypdf(self, file_path) -> PDFProcessResult:
        """无 PyMuPDF 时降级到 pypdf（仅支持原生文本抽取）"""
        result = PDFProcessResult()
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            result.total_pages = len(reader.pages)
            for i, page in enumerate(reader.pages):
                t = page.extract_text() or ""
                result.pages.append(PDFPage(
                    index=i + 1,
                    page_type="native",
                    text=t.strip(),
                    source=str(file_path),
                ))
                result.native_pages += 1
            logger.info("⚠️  使用 pypdf 降级模式（仅原生文本抽取）")
        except ImportError:
            result.failed = True
            result.error = "需要 PyMuPDF 或 pypdf 库"
        except Exception as e:
            result.failed = True
            result.error = str(e)
        return result
