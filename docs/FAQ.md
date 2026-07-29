# ❓ 常见问题 FAQ

> 高频报错、环境问题、使用疑问的快速排查指南。

---

## 1. 安装与环境

### Q1: `pip install -r requirements.txt` 安装失败

**可能原因**:
- 网络问题,包下载失败
- Python 版本不兼容
- 某些包编译失败(如 FAISS)

**解决方案**:
```bash
# 1. 升级 pip
pip install --upgrade pip

# 2. 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 如果 FAISS 安装失败,用预编译包
pip install faiss-cpu --no-cache-dir

# 4. 检查 Python 版本(需要 >= 3.10)
python --version
```

### Q2: `ModuleNotFoundError: No module named 'xxx'`

**可能原因**:
- 依赖没安装全
- 虚拟环境没激活
- Python 路径问题

**解决方案**:
```bash
# 1. 确认虚拟环境已激活
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

# 2. 重新安装依赖
pip install -r requirements.txt

# 3. 确认使用的是虚拟环境的 Python
which python  # Mac/Linux
where python  # Windows
```

### Q3: LangChain 版本冲突

**报错类似**:
```
ImportError: cannot import name 'create_agent' from 'langchain.agents'
```

**解决方案**:
```bash
# 先卸载所有 langchain 相关包
pip uninstall -y langchain langchain-core langchain-community langchain-experimental langgraph

# 重新安装(指定版本范围)
pip install "langchain>=0.3.0,<0.4.0" "langchain-core>=0.3.0,<0.4.0" "langchain-community>=0.3.0,<0.4.0" "langgraph>=0.2.0,<0.3.0"
```

---

## 2. API 与 LLM

### Q4: API Key 配置后仍报错"未配置"

**报错**:
```
ValueError: 请配置 DASHSCOPE_API_KEY
```

**解决方案**:
1. 确认 `.env` 文件在项目根目录
2. 确认 key 没有引号和空格:
   ```bash
   # ✅ 正确
   DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
   
   # ❌ 错误(有引号)
   DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxx"
   ```
3. 确认文件编码为 UTF-8
4. 重启 Python 进程(修改 .env 后不会自动 reload)

### Q5: LLM 调用超时

**报错**:
```
ConnectionError: 调用超时
```

**解决方案**:
1. 检查网络是否能访问阿里云
   ```bash
   ping dashscope.aliyuncs.com
   ```
2. 增大超时时间(修改 `.env`):
   ```bash
   LLM_TIMEOUT=120
   ```
3. 检查是否被限流(429 错误),降低请求频率
4. 配置代理(如果需要):
   ```bash
   # .env 中添加
   HTTPS_PROXY=http://proxy:port
   ```

### Q6: API 返回 401/403 鉴权失败

**解决方案**:
1. 检查 API Key 是否正确(复制时不要带多余空格)
2. 确认 Key 没有过期
3. 确认账号有对应模型的访问权限
4. 确认账户余额充足

### Q7: 触发限流(429 Too Many Requests)

**解决方案**:
1. 降低请求频率(默认每分钟 60 次)
2. 开启限流保护:
   ```bash
   LLM_RATE_LIMIT_ENABLED=true
   LLM_RATE_LIMIT_PER_MINUTE=30
   ```
3. 增加重试次数:
   ```bash
   LLM_RETRY_TIMES=5
   ```

---

## 3. 数据库

### Q8: `sqlite3.OperationalError: no such table: xxx`

**原因**:数据库未初始化或表不存在。

**解决方案**:
```bash
# 重新初始化数据
python init_data.py
```

### Q9: 数据库被锁定(database is locked)

**原因**:SQLite 是单写多读,多个写操作同时进行会锁库。

**解决方案**:
1. 确保没有多个进程同时写数据库
2. 增加超时时间(在 `db_client.py` 中):
   ```python
   conn = sqlite3.connect(db_path, timeout=30)
   ```
3. 高并发场景建议迁移到 PostgreSQL(见 [部署指南](./deployment/DEPLOYMENT.md#数据库迁移))

### Q10: SQL 执行结果为空

**可能原因**:
- SQL 语法错误(但没报错)
- 查询条件太严格
- 表里没数据

**排查步骤**:
```bash
# 1. 先确认表里有数据
python -c "import sqlite3; conn=sqlite3.connect('data/finance.db'); print(conn.execute('SELECT COUNT(*) FROM stocks').fetchone())"

# 2. 打开 SQL 日志,看生成的 SQL 是什么
# 在 cli.py 中添加 print(sql)

# 3. 把生成的 SQL 拿到数据库客户端直接执行,看结果
```

---

## 4. 向量库与 RAG

### Q11: FAISS 索引加载失败

**报错类似**:
```
RuntimeError: Error in faiss::Index* ...
```

**可能原因**:
- 索引文件损坏
- 维度不匹配(1536 维的索引用 1024 维模型查询)
- FAISS 版本不兼容

**解决方案**:
```bash
# 1. 删除旧索引,重新构建
rm -rf data/faiss_index
python init_data.py

# 2. 确认 Embedding 维度与索引一致
# .env 中 EMBEDDING_DIMENSION 必须和构建索引时的维度相同

# 3. 重新安装 FAISS
pip uninstall -y faiss-cpu
pip install faiss-cpu --no-cache-dir
```

### Q12: 召回的文档完全不相关

**可能原因**:
- 查询词太短或太模糊
- 文档内容太少
- Embedding 模型不匹配
- 切分不合理

**排查步骤**:
1. 用更具体的关键词测试:
   ```
   ❌ "茅台怎么样" (太泛)
   ✅ "茅台 2024年 营收预测" (具体)
   ```
2. 检查文档是否真的被正确索引:
   ```bash
   # 查看索引了多少个 chunk
   python -c "import faiss; index = faiss.read_index('data/faiss_index/index.faiss'); print('chunk总数:', index.ntotal)"
   ```
3. 调整 TopK 和相似度阈值:
   ```bash
   FAISS_TOP_K=10
   # 然后在结果中自己筛选高分的
   ```
4. 尝试不同的切分参数(见 [RAG 调优指南](./rag/RAG_TUNING.md))

### Q13: PDF 解析乱码/内容不对

**可能原因**:
- 扫描版 PDF(图片),无法直接提取文字
- 特殊字体导致编码问题
- PDF 有加密

**解决方案**:
1. 确认是文字版 PDF 还是扫描版 PDF:
   - 能用鼠标选中文字 → 文字版(可解析)
   - 不能选中 → 扫描版(需 OCR)
2. 扫描版 PDF 需要 OCR:
   ```bash
   # 安装 OCR 工具(如 PaddleOCR)
   pip install paddleocr paddlepaddle
   ```
3. 加密 PDF 需要先解密

### Q14: 大文档(>100 页)检索效果差

**原因**:文档太长,关键信息分散在多个 chunk 中,召回不全。

**解决方案**:
1. 用「父子文档」策略(见 [RAG 调优指南](./rag/RAG_TUNING.md#64-父子文档parent-child-chunking))
2. 先做文档摘要,检索时先匹配摘要,再取对应全文
3. 增加 TopK 数量
4. 用 Rerank 重排

---

## 5. FastAPI 与 Streamlit

### Q15: FastAPI 启动失败,端口被占用

**报错**:
```
OSError: [WinError 10048] 通常每个套接字地址(协议/网络地址/端口)只允许使用一次。
```

**解决方案**:
```bash
# 1. 换个端口
uvicorn api:app --port 8001

# 2. 查找并杀掉占用端口的进程
# Windows:
netstat -ano | findstr :8000
taskkill /PID <进程ID> /F

# Mac/Linux:
lsof -i :8000
kill -9 <进程ID>
```

### Q16: Streamlit 页面一直在转圈圈

**可能原因**:
- 后端 API 没启动
- 网络不通
- LLM 调用太慢

**排查**:
1. 确认 FastAPI 已启动:访问 http://localhost:8000/health
2. 打开浏览器开发者工具 → Network,看请求状态
3. 检查 API 地址配置是否正确

### Q17: 流式输出不生效

**可能原因**:
- 用了同步接口而不是 SSE
- 代理或 CDN 缓存了响应
- 浏览器不支持

**解决方案**:
1. 确认调用的是 `/analyze/stream` 接口,不是 `/analyze`
2. 直接访问确认 SSE 有效:
   ```bash
   curl -N -X POST http://localhost:8000/analyze/stream \
     -H "Content-Type: application/json" \
     -d '{"query": "你好"}'
   ```
3. Nginx 反代需要加配置:
   ```nginx
   proxy_buffering off;
   proxy_cache off;
   ```

---

## 6. 性能与优化

### Q18: 查询太慢,要等十几秒

**性能瓶颈排查**:
1. 确认哪一步最慢(SQL 生成 / RAG 检索 / LLM 生成)
2. 查看 usage 中的 latency_ms
3. 针对性优化:

| 瓶颈 | 优化方案 |
|------|---------|
| LLM 生成慢 | 用更快的模型(qwen-turbo)、流式输出 |
| RAG 检索慢 | 切换 IVF/HNSW 索引、减小索引规模 |
| SQL 执行慢 | 加索引、优化查询语句 |
| 整体慢 | SQL 和 RAG 并行执行 |

### Q19: 内存占用过高

**可能原因**:
- FAISS 索引太大(文档太多)
- LLM 上下文太长

**解决方案**:
1. 减小索引规模或切换向量库
2. 限制召回文档数量和长度
3. 用更轻量的 Embedding 模型(更小维度)

---

## 7. 其他

### Q20: 如何重置所有数据,重新开始?

```bash
# 删除数据目录
rm -rf data/

# 重新初始化
python init_data.py
```

### Q21: 如何更换主题行业/数据?

修改 `init_data.py` 中的模拟数据生成逻辑,然后重新初始化:
```bash
python init_data.py --force  # 强制重建
```

### Q22: Windows 上的特殊问题

**问题**:路径分隔符、编码、signal 等差异。

**常见解决方案**:
1. 文件路径用 `pathlib.Path` 或正斜杠 `/`
2. 控制台中文乱码:设置编码为 UTF-8
   ```bash
   chcp 65001
   set PYTHONIOENCODING=utf-8
   ```
3. SQLite 超时控制改用 `conn.execute("PRAGMA busy_timeout = 30000")` 而不是 signal

### Q23: 如何贡献代码?

见 [扩展开发指南](./extend/EXTEND_GUIDE.md#8-代码风格与规范)

---

## 8. 问题排查通用步骤

遇到任何问题,按以下顺序排查:

1. **看错误信息** — 仔细读报错,错误信息通常已经告诉你原因
2. **检查环境** — Python 版本、依赖版本、虚拟环境
3. **确认配置** — `.env` 文件是否存在、key 是否正确
4. **复现问题** — 最小化复现步骤,定位触发条件
5. **搜索错误** — 把错误信息复制到搜索引擎
6. **查看日志** — 打开 debug 日志,看中间输出
7. **回退版本** — 如果是升级后出问题,回退到可用版本

---

## 9. 还没找到答案?

1. 先确认项目版本: `git log --oneline -1`
2. 查看详细架构文档: [架构设计文档](./architecture/ARCHITECTURE.md)
3. 查阅安全规范: [SQL 安全规范](./architecture/SECURITY.md)
4. RAG 相关: [RAG 调优指南](./rag/RAG_TUNING.md)
5. 部署相关: [部署运维指南](./deployment/DEPLOYMENT.md)
