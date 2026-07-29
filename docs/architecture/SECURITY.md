# 🛡️ SQL 安全执行规范

> 详细说明 SQL 安全执行器的 6 层防护机制、配置方式、测试用例与绕过风险。

---

## ⚠️ 安全声明

尽管有多层防护,但**没有绝对的安全**。请务必注意:
- 生产环境建议使用**独立的只读数据库用户**,权限最小化
- 不要将本系统直接暴露给不可信用户(如公开互联网)
- 定期审计 SQL 执行日志,发现异常及时拦截
- 本防护机制仅适用于 SQLite,迁移到其他数据库需重新评估

---

## 1. 防护架构总览

`executor.py` 采用 **6 层纵深防御** 架构,从外到内逐层过滤:

```
用户输入 → LLM 生成 SQL
            ↓
    ┌───────────────────┐
    │ 第 1 层: 关键字过滤 │  正则匹配,快速拦截明显恶意 SQL
    └─────────┬─────────┘
              ↓
    ┌───────────────────┐
    │ 第 2 层: 语法校验   │  sqlparse 解析 AST,确认类型为 SELECT
    └─────────┬─────────┘
              ↓
    ┌───────────────────┐
    │ 第 3 层: 只读事务   │  SQLite 连接开启只读模式
    └─────────┬─────────┘
              ↓
    ┌───────────────────┐
    │ 第 4 层: 行数限制   │  自动追加 LIMIT 1000
    └─────────┬─────────┘
              ↓
    ┌───────────────────┐
    │ 第 5 层: 超时控制   │  30 秒超时,防止复杂查询卡死
    └─────────┬─────────┘
              ↓
    ┌───────────────────┐
    │ 第 6 层: 权限隔离   │  数据库文件仅 SELECT 权限
    └─────────┬─────────┘
              ↓
          执行查询 → 返回结果
```

---

## 2. 各层防护详解

### 2.1 第 1 层:关键字过滤

**机制**:用正则表达式匹配 SQL 中的禁用关键字。

**禁用关键字清单**:
```sql
-- DDL (数据定义语言)
DROP, ALTER, CREATE, TRUNCATE, RENAME

-- DML (数据操作语言)
INSERT, UPDATE, DELETE, REPLACE, MERGE

-- 权限控制
GRANT, REVOKE

-- 其他危险操作
EXEC, EXECUTE, xp_cmdshell, INTO OUTFILE, LOAD_FILE
```

**实现方式**:
```python
FORBIDDEN_KEYWORDS = [
    'DROP', 'ALTER', 'CREATE', 'TRUNCATE', 'RENAME',
    'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'MERGE',
    'GRANT', 'REVOKE',
    'EXEC(', 'EXECUTE(', 'xp_cmdshell', 'INTO OUTFILE', 'LOAD_FILE',
]

def _keyword_check(sql: str) -> None:
    sql_upper = sql.upper()
    for kw in FORBIDDEN_KEYWORDS:
        if kw in sql_upper:
            raise SecurityError(f"检测到禁用关键字: {kw}")
```

**局限性**:
- 容易被注释绕过: `SEL/*comment*/ECT`
- 容易被编码绕过: `CHAR(68,82,79,80)`
- 仅作第一道快速过滤,不能单独依赖

### 2.2 第 2 层:语法校验

**机制**:用 `sqlparse` 解析 SQL 语法树(AST),确认语句类型。

**校验规则**:
- 必须是 `SELECT` 语句
- 不能包含多个语句(防止 `SELECT ...; DROP TABLE ...`)
- 子查询也必须是 SELECT 类型

**实现方式**:
```python
import sqlparse

def _syntax_check(sql: str) -> None:
    parsed = sqlparse.parse(sql)
    if len(parsed) != 1:
        raise SecurityError("不允许多条语句")

    stmt = parsed[0]
    stmt_type = stmt.get_type()
    if stmt_type != 'SELECT':
        raise SecurityError(f"仅支持 SELECT 语句,当前为: {stmt_type}")
```

**局限性**:
- `sqlparse` 不是完整 SQL 解析器,复杂 SQL 可能解析错误
- SQLite 的某些方言语法可能不被识别

### 2.3 第 3 层:只读事务

**机制**:SQLite 连接开启 `PRAGMA query_only = TRUE`,即使 SQL 绕过了前两层检查,也无法写入数据。

**实现方式**:
```python
def _get_readonly_connection(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path)
    conn.execute("PRAGMA query_only = TRUE")
    conn.execute("PRAGMA read_uncommitted = FALSE")
    return conn
```

**防护效果**:
- DDL/DML 语句直接报错: `attempt to write a readonly database`
- 即使攻击者绕过了前两层,也无法修改数据
- 这是最可靠的一层防护

### 2.4 第 4 层:行数限制

**机制**:自动追加 `LIMIT N`,防止全表扫描或超大结果集拖垮系统。

**实现方式**:
```python
def _enforce_limit(sql: str, max_rows: int) -> str:
    # 如果已经有 LIMIT,检查是否超过 max_rows
    if 'LIMIT' in sql.upper():
        # 解析 LIMIT 值,如果超过则替换
        ...
    else:
        # 追加 LIMIT
        sql = sql.rstrip().rstrip(';') + f" LIMIT {max_rows}"
    return sql
```

**配置项**:
- `DB_MAX_ROWS=1000` — 默认最大返回 1000 行

### 2.5 第 5 层:超时控制

**机制**:设置查询超时,防止复杂 SQL(如笛卡尔积)无限执行。

**实现方式**:
```python
import signal

class QueryTimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise QueryTimeoutError("查询超时")

def execute_with_timeout(sql: str, timeout: int = 30):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)
    try:
        result = conn.execute(sql).fetchall()
    finally:
        signal.alarm(0)  # 取消超时
    return result
```

> ⚠️ 注意:Windows 上 `signal.SIGALRM` 不可用,改用线程超时方案。

**配置项**:
- `DB_TIMEOUT=30` — 默认 30 秒超时

### 2.6 第 6 层:权限隔离

**机制**:操作系统层面限制数据库文件的权限,确保进程只有读权限。

**配置方式**(Linux/Mac):
```bash
# 设置数据目录只读
chmod 555 data/
chmod 444 data/finance.db
```

**配置方式**(Windows):
```powershell
# 设置文件只读属性
Set-ItemProperty data\finance.db -Name IsReadOnly -Value $true
```

> 这是最后一道防线,即使前面所有层都被绕过,操作系统也会阻止写入。

---

## 3. 配置项汇总

| 配置项 | 默认值 | 说明 | 所在层 |
|--------|-------|------|--------|
| `DB_READONLY` | `true` | 是否启用只读模式 | 第 3 层 |
| `DB_MAX_ROWS` | `1000` | 单查询最大返回行数 | 第 4 层 |
| `DB_TIMEOUT` | `30` | 查询超时时间(秒) | 第 5 层 |

---

## 4. 测试用例

### 4.1 注入攻击测试用例

| 测试用例 | 预期结果 | 测试层 |
|---------|---------|--------|
| `SELECT * FROM stocks; DROP TABLE stocks;` | 拒绝:多语句 | 第 2 层 |
| `DROP TABLE stocks` | 拒绝:禁用关键字 | 第 1 层 |
| `DELETE FROM stocks WHERE 1=1` | 拒绝:禁用关键字 | 第 1 层 |
| `INSERT INTO stocks VALUES (...)` | 拒绝:禁用关键字 | 第 1 层 |
| `UPDATE stocks SET name='test' WHERE 1=1` | 拒绝:禁用关键字 | 第 1 层 |
| `SELECT * FROM users WHERE id=1; DROP TABLE users--` | 拒绝:多语句 | 第 2 层 |
| `SELECT * FROM stocks UNION SELECT null, null, null--` | 通过(UNION 是只读的) | - |
| `SELECT * FROM stocks WHERE 1=1` | 通过 | - |

### 4.2 运行测试

```bash
pytest tests/test_executor.py -v
```

预期结果:15+ 个测试用例全部通过。

---

## 5. 已知风险与绕过可能性

### 5.1 可能绕过的场景

| 攻击方式 | 能否绕过 | 说明 | 防护建议 |
|---------|---------|------|---------|
| 注释混淆 (`DROP/*...*/`) | 第 1 层能绕过 | 关键字匹配不考虑注释 | 第 2 层 AST 校验会拦截 |
| Unicode 编码绕过 | 第 1 层可能绕过 | 特殊字符可能绕过正则 | 第 2/3 层兜底 |
| 大小写混合绕过 | 不能 | 已统一转大写比较 | - |
| SQLite 特殊语法 | 可能 | `ATTACH`, `VACUUM` 等 | 关键字列表已覆盖常见危险操作 |
| 逻辑炸弹(超长 SQL) | 可能 | 解析器可能崩溃 | 超时控制 + 输入长度限制 |

### 5.2 生产环境增强建议

如果需要在生产环境使用,建议增加:

1. **WAF 层**:在 API 网关增加 SQL 注入检测规则
2. **审计日志**:记录所有执行的 SQL,定期审计
3. **异常检测**:基于历史行为,检测异常查询模式
4. **数据库用户权限**:使用最小权限的数据库账户
5. **查询白名单**:对常见查询做白名单,未命中的拒绝
6. **人工审核**:对高风险查询增加人工审核流程

---

## 6. 与其他数据库的兼容性

| 数据库 | 只读事务 | 关键字过滤 | 语法校验 | 迁移难度 |
|--------|---------|-----------|---------|---------|
| SQLite | ✅ `PRAGMA query_only` | ✅ 通用 | ⚠️ sqlparse 基本支持 | - |
| MySQL | ✅ 只读用户 | ✅ 通用 | ⚠️ 需调整解析规则 | ★★☆ |
| PostgreSQL | ✅ 只读事务 + 只读用户 | ✅ 通用 | ⚠️ 需调整解析规则 | ★★☆ |
| ClickHouse | ✅ 只读用户 | ✅ 通用 | ❌ 语法差异大 | ★★★ |

迁移指南见 [部署运维指南 → 数据库迁移](../deployment/DEPLOYMENT.md#数据库迁移)。

---

## 7. 相关文件

| 文件 | 说明 |
|------|------|
| `executor.py` | SQL 安全执行器实现 |
| `db_client.py` | 数据库连接管理 |
| `config.py` | 配置中心(DB 相关配置) |
| `tests/test_executor.py` | 安全测试用例 |
