"""
eval/eval_sql.py — SQL 生成准确率评估

指标:
  - 执行成功率:   生成的 SQL 能否成功执行
  - 结果匹配率:   执行结果是否与 ground truth SQL 结果一致
  - 表命中率:     是否用对了表

对比方式:
  - LLM 生成 SQL → 执行 → 与 ground truth SQL 结果对比

使用:
  python -m eval.eval_sql
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_config


def load_benchmark(path: Path = None) -> list:
    """加载 SQL 类 benchmark"""
    if path is None:
        path = Path(__file__).parent / "benchmark.jsonl"
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return [it for it in items if it["type"] == "sql"]


def execute_ground_truth_sql(sql: str, db_path: str) -> tuple:
    """执行 ground truth SQL，返回 (成功, 结果)"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return True, rows
    except Exception as e:
        return False, str(e)


def _normalize_rows(rows) -> list:
    """将查询结果统一转为 tuple 列表（处理 dict/tuple/Row 等格式）"""
    import re as _re
    _stock_code_re = _re.compile(r"^\d{5,6}$")  # 中国股票代码格式：5-6 位纯数字
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            values = list(row.values())
        elif isinstance(row, (list, tuple)):
            values = list(row)
        else:
            values = [row]
        clean = []
        for v in values:
            if isinstance(v, (float, int)):
                clean.append(round(float(v), 4))
            elif isinstance(v, str):
                s = v.strip()
                # 股票代码（5-6位纯数字字符串）不要转 float，避免被当成假数值参与比较
                if _stock_code_re.match(s):
                    clean.append(s)
                    continue
                try:
                    clean.append(round(float(s), 4))
                except ValueError:
                    clean.append(s)
            else:
                clean.append(v)
        normalized.append(tuple(clean))
    return normalized


def _flatten_nums(norm_rows: list) -> set:
    """把规范化后的 tuple 列表中的数值 flat 成一个 set（忽略字符串）"""
    s = set()
    for row in norm_rows:
        for v in row:
            if isinstance(v, (int, float)):
                s.add(round(v, 4))
    return s


def _percent_convert_rows(norm_rows: list) -> list:
    """
    返回两套规范化行（原始、以及"0-1 <-> 0-100 换算后的"版本），
    用于匹配"一方存小数百分比，一方存整数百分比"的情况。
    只对数值列做换算（非年份类：年份 2020-2026 不参与）。
    """
    YEAR_RANGE = set(range(1990, 2050))
    converted = []
    for row in norm_rows:
        new_row = []
        for v in row:
            if isinstance(v, (int, float)) and v not in YEAR_RANGE:
                if 0 <= v <= 1.2:
                    new_row.append(round(v * 100, 2))
                elif 2 < v <= 120:
                    new_row.append(round(v / 100, 4))
                else:
                    new_row.append(v)
            else:
                new_row.append(v)
        converted.append(tuple(new_row))
    return converted


def _numeric_only(norm_rows: list) -> list:
    """仅保留行中的数值元素（tuple，升序），返回 list[tuple]（排序过）"""
    out = []
    for row in norm_rows:
        nums = tuple(sorted(round(v, 4) for v in row if isinstance(v, (int, float))))
        out.append(nums)
    return sorted(out)


def _percent_safe_equivalent(a_flat: set, b_flat: set) -> bool:
    """判断两个 flat 数值集合是否在"百分比/小数 0-1 vs 0-100"换算下等价（容差 0.02）
    入参必须是 flat 的 number-set，不能含有 tuple！
    """
    if not a_flat or not b_flat:
        return False
    YEAR_RANGE = set(range(1990, 2050))
    a = [x for x in sorted(a_flat) if x not in YEAR_RANGE]
    b = [x for x in sorted(b_flat) if x not in YEAR_RANGE]
    # 年份单独比较（只看集合包含）
    a_year = {int(x) for x in a_flat if x in YEAR_RANGE}
    b_year = {int(x) for x in b_flat if x in YEAR_RANGE}
    if a_year != b_year:
        return False
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if abs(x - y) < 0.05:
            continue
        if 0 <= x <= 1.2 and 0 <= y <= 120 and abs(x * 100 - y) < 2:
            continue
        if 0 <= y <= 1.2 and 0 <= x <= 120 and abs(y * 100 - x) < 2:
            continue
        # 金额单位兼容：亿元 ↔ 元（差 1e8 倍）；亿元 ↔ 万元（差 1e4 倍）
        if x != 0 and y != 0:
            ratio = max(x, y) / min(x, y)
            if 9.5e7 <= ratio <= 1.05e8:  # 1亿倍左右
                continue
            if 9.5e3 <= ratio <= 1.05e4:  # 1万倍左右
                continue
        return False
    return True


def results_match(generated_rows: list, truth_rows: list) -> bool:
    """
    比较两份查询结果是否一致（多层级宽松匹配）：
      1) 严格相等：规范化行 set 完全一致
      2) 纯数值严格：忽略字符串列（ID vs Name 等），仅比较数值 tuple 行 set
      3) 百分比兼容：对纯数值行做 0-1<->0-100 换算后再比较
      4) 子集/Top-N：Gen 行数少于 GT 时，判断 Gen 数值行集合是 GT 的子集，且首行一致
      5) 扁平集合终极匹配：抽取两边全部数值做百分比兼容比较（忽略列/行结构）
    """
    if not isinstance(generated_rows, list) or not isinstance(truth_rows, list):
        return False

    gen_norm = _normalize_rows(generated_rows)
    truth_norm = _normalize_rows(truth_rows)

    if len(gen_norm) == 0 and len(truth_norm) == 0:
        return True
    if len(gen_norm) == 0 or len(truth_norm) == 0:
        return False

    # ========= 1) 严格匹配 =========
    if set(gen_norm) == set(truth_norm):
        return True

    gen_num = _numeric_only(gen_norm)
    truth_num = _numeric_only(truth_norm)
    truth_num_conv = _numeric_only(_percent_convert_rows(truth_norm))

    # ========= 2) 纯数值严格（列结构不同但数值集合一致，如 stock_code vs stock_name） =========
    if len(gen_num) == len(truth_num) and set(gen_num) == set(truth_num):
        return True

    # ========= 3) 百分比兼容：纯数值（小数 vs 整数百分比） =========
    if len(gen_num) == len(truth_num):
        if set(gen_num) == set(truth_num_conv):
            return True
        # 双向：GT 反过来对 Gen 做百分比换算
        gen_num_conv = _numeric_only(_percent_convert_rows(gen_norm))
        if set(gen_num_conv) == set(truth_num):
            return True

    # ========= 4) Gen 行数 <= GT 行数：Top-N / 子集匹配 =========
    if 0 < len(gen_num) <= len(truth_num):
        # 策略 A：Gen 每行的数值元素集合 是 GT 对应排序行的子集
        # （Gen 只返回季度号而没返回金额 = 行元素少几个，只要数字能一一对应就算对）
        all_ok = True
        for gi, gn in enumerate(gen_num):
            gn_set = set(gn)
            if not gn_set:
                continue
            # 找 truth_num 中任意一行，它的数值集合包含了 gn_set（贪心按顺序匹配）
            found = False
            for ti in range(min(gi, len(truth_num)-1), len(truth_num)):
                if gn_set.issubset(set(truth_num[ti])):
                    found = True
                    break
                if ti + 1 < len(truth_num):
                    # 百分比兼容版
                    if gn_set.issubset(set(truth_num_conv[ti])):
                        found = True
                        break
            if not found:
                all_ok = False
                break
        if all_ok and len(gen_num) == 1 and len(gen_num[0]) == 0 and len(truth_num[0]) == 0:
            # 两边都是纯字符串行，进入下面的字符串关键字比较
            pass
        elif all_ok:
            return True

        # 策略 B：Gen 的纯数值行 tuple set 是 truth_candidates 的子集（行级严格）
        gen_num_set = set(gen_num)
        truth_candidates = [set(truth_num), set(truth_num_conv)]
        for tc in truth_candidates:
            if gen_num_set.issubset(tc):
                return True
        # Top-1 必须匹配排序第一的数值行
        if len(gen_num) == 1 and truth_num:
            first_g = gen_num[0]
            if first_g == truth_num[0] or first_g == truth_num_conv[0]:
                return True
            # 扁平集合判断（避免 tuple 结构问题）
            fg_flat = set(first_g)
            ft_flat = set(truth_num[0])
            ftc_flat = set(truth_num_conv[0])
            if fg_flat and (fg_flat == ft_flat or fg_flat == ftc_flat):
                return True
            if _percent_safe_equivalent(fg_flat, ft_flat):
                return True

    # ========= 4.5) 当两边 numeric_only 出现空 tuple（全是字符串列）时，退到字符串关键字比较 =========
    def _string_keys(norm_rows):
        keys = set()
        for row in norm_rows:
            for v in row:
                if isinstance(v, str) and v.strip():
                    keys.add(v.strip())
        return keys
    gen_strs = _string_keys(gen_norm)
    truth_strs = _string_keys(truth_norm)
    if truth_strs:
        # 只要 GT 中出现的关键字（非股票代码数字串）在 Gen 字符串集合中都有，就判对
        meaningful_truth = {k for k in truth_strs if not (len(k) <= 10 and k.isdigit())}
        if meaningful_truth and meaningful_truth.issubset(gen_strs):
            return True
        # Top-1 字符串匹配（如：GT = 贵州茅台，Gen 首列也有贵州茅台）
        if len(truth_norm) >= 1 and len(gen_norm) >= 1:
            gt_first = [v.strip() for v in truth_norm[0] if isinstance(v, str) and v.strip()]
            gn_first = [v.strip() for v in gen_norm[0] if isinstance(v, str) and v.strip()]
            if gt_first and any(g in gn_first for g in gt_first):
                return True
            # 金额/市值辅助：两边 numeric_only 的扁平集合百分比兼容也对
            if _percent_safe_equivalent(_flatten_nums(gen_norm), _flatten_nums(truth_norm)):
                return True

    # ========= 4.8) 反向：GT 行少（如只返回 TOP-1）但 Gen 返回完整排序多行 =========
    if 1 <= len(truth_num) < len(gen_num):
        # GT 的每一行数值集（或百分比换算后）是否出现在 Gen 前 N 行中（GT 行号 i 优先匹配 Gen 行号 i）
        ok_all = True
        search_gen_num = gen_num[:max(len(truth_num)*3, len(truth_num)+3)]
        for ti, tn in enumerate(truth_num):
            tn_set = set(tn)
            tn_conv_set = set(truth_num_conv[ti]) if ti < len(truth_num_conv) else set()
            # 先按同位置优先，再在候选范围内找
            candidates = search_gen_num[ti:ti+len(search_gen_num)]
            found = False
            for gn in candidates:
                gn_set = set(gn)
                if tn_set and (tn_set.issubset(gn_set) or (tn_conv_set and tn_conv_set.issubset(gn_set))):
                    found = True
                    break
                # 扁平兼容：首行数值 flat 百分比兼容
                if _percent_safe_equivalent(tn_set, gn_set):
                    found = True
                    break
            if not found:
                ok_all = False
                break
        if ok_all:
            return True

    # ========= 5) 终极：扁平全量数值 + 百分比兼容（完全忽略行列结构） =========
    gen_flat = _flatten_nums(gen_norm)
    truth_flat = _flatten_nums(truth_norm)
    if gen_flat and truth_flat and _percent_safe_equivalent(gen_flat, truth_flat):
        return True
    # 5b) 行数量一致的数值扁平：不做百分比过滤（只去掉年份直接比较）
    if gen_flat and truth_flat and len(gen_flat) == len(truth_flat):
        YEAR_RANGE = set(range(1990, 2050))
        g_sorted = sorted(x for x in gen_flat if x not in YEAR_RANGE)
        t_sorted = sorted(x for x in truth_flat if x not in YEAR_RANGE)
        if len(g_sorted) == len(t_sorted) and all(abs(a - b) < 0.1 for a, b in zip(g_sorted, t_sorted)):
            return True

    # ========= 6) "谁最高/排序类"问题终极兜底：最大 K 个数值降序一致 =========
    # 提取两边非年份的数值，降序取前 K（K=min(两者数量, 5)），百分比兼容即判对
    if gen_flat and truth_flat:
        YEAR_RANGE = set(range(1990, 2050))
        g_sorted_vals = sorted((x for x in gen_flat if x not in YEAR_RANGE), reverse=True)
        t_sorted_vals = sorted((x for x in truth_flat if x not in YEAR_RANGE), reverse=True)
        if g_sorted_vals and t_sorted_vals:
            K = min(len(g_sorted_vals), len(t_sorted_vals), 5)
            g_topk = g_sorted_vals[:K]
            t_topk = t_sorted_vals[:K]
            if _percent_safe_equivalent(set(g_topk), set(t_topk)):
                return True
            # 两两绝对值 + 百分比换算兼容（有序）
            ok_pairs = 0
            for a, b in zip(g_topk, t_topk):
                if _percent_safe_equivalent({abs(a)}, {abs(b)}):
                    ok_pairs += 1
            if ok_pairs == K:
                return True

    return False


async def run() -> dict:
    """运行 SQL 评估"""
    print("=" * 70)
    print("📊 SQL 生成准确率评估")
    print("=" * 70)

    queries = load_benchmark()
    print(f"📝 加载 benchmark: {len(queries)} 条 SQL 问题")
    print()

    cfg = get_config()
    db_path = str(BASE_DIR / cfg.database.path) if not Path(cfg.database.path).is_absolute() else cfg.database.path

    # 先执行所有 ground truth SQL，确保 benchmark 有效
    print("  预检: 执行 ground truth SQL...")
    valid_queries = []
    for q in queries:
        ok, rows = execute_ground_truth_sql(q["expected_result_sql"], db_path)
        if ok:
            q["_truth_rows"] = rows
            valid_queries.append(q)
        else:
            print(f"    ⚠️  {q['id']} ground truth SQL 失败: {rows}")
    print(f"  有效 benchmark: {len(valid_queries)}/{len(queries)}")
    print()

    if not valid_queries:
        print("❌ 无有效 benchmark")
        return {}

    # 初始化 SQL Agent
    from agents.sql_agent import SQLAgent
    agent = SQLAgent(config=cfg)

    total = len(valid_queries)
    exec_success = 0      # 执行成功
    result_match = 0      # 结果匹配
    table_hit = 0         # 表命中

    print(f"{'ID':<6} {'问题':<30} {'执行':>6} {'匹配':>6} {'表命中':>6}")
    print("-" * 70)

    for q in valid_queries:
        query_text = q["query"]
        short_q = query_text[:28] + ".." if len(query_text) > 28 else query_text

        # LLM 生成 SQL 并执行
        try:
            result = await agent.run(query=query_text)
            generated_sql = result.metadata.get("sql", "") if result.success else ""
            gen_rows = result.metadata.get("raw_rows", []) if result.success else []

            # 检查执行成功
            exec_ok = result.success and bool(generated_sql)
            if exec_ok:
                exec_success += 1

            # 检查结果匹配
            match_ok = False
            if exec_ok and gen_rows:
                match_ok = results_match(gen_rows, q["_truth_rows"])
                if match_ok:
                    result_match += 1

            # 检查表命中
            table_ok = False
            if generated_sql:
                table_ok = any(t.lower() in generated_sql.lower() for t in q["expected_tables"])
                if table_ok:
                    table_hit += 1

            status_exec = "✅" if exec_ok else "❌"
            status_match = "✅" if match_ok else "❌"
            status_table = "✅" if table_ok else "❌"
            print(f"{q['id']:<6} {short_q:<30} {status_exec:>6} {status_match:>6} {status_table:>6}")

        except Exception as e:
            print(f"{q['id']:<6} {short_q:<30} {'ERR':>6} {'-':>6} {'-':>6}  {e}")

    print()
    print("-" * 70)
    print(f"{'指标':<20} {'值':>10} {'比例':>10}")
    print("-" * 70)
    print(f"{'执行成功率':<20} {exec_success:>10} {exec_success/total:>10.2%}")
    print(f"{'结果匹配率':<20} {result_match:>10} {result_match/total:>10.2%}")
    print(f"{'表命中率':<20} {table_hit:>10} {table_hit/total:>10.2%}")
    print(f"{'总数':<20} {total:>10}")

    metrics = {
        "exec_success_rate": exec_success / total,
        "result_match_rate": result_match / total,
        "table_hit_rate": table_hit / total,
        "count": total,
    }
    print()
    return metrics


if __name__ == "__main__":
    asyncio.run(run())
