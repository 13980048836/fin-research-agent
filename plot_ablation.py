"""
生成 RAG 消融实验图表和 SQL 指标表图。
- 图1：RAG 5种策略 Recall@5 / Precision@5 对比柱状图
- 图2：RAG 5种策略 MRR / Hit@5 对比柱状图
- 图3：SQL 三大评估指标（执行成功率/结果匹配率/表命中率）

保存到 docs/ 目录
"""
import os
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

# 真实评估数据（2026-07-30 70题 benchmark）
RAG_STRATEGIES = ["纯向量(FAISS)", "纯BM25", "混合(RRF)", "混合+MMR", "混合(完整)"]
RECALL5 = [1.0000, 0.9474, 1.0000, 0.8158, 0.8158]
PREC5   = [0.2105, 0.2000, 0.2105, 0.1684, 0.1684]
MRR     = [0.9307, 0.7895, 0.7377, 0.6408, 0.6408]
HIT5    = [1.0000, 0.9474, 1.0000, 0.8421, 0.8421]

SQL_METRICS = ["执行成功率", "结果匹配率", "表命中率"]
SQL_VALUES  = [1.0, 1.0, 1.0]

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
os.makedirs(OUT_DIR, exist_ok=True)

# ========== 图 1: Recall@5 / Precision@5 ==========
x = list(range(len(RAG_STRATEGIES)))
w = 0.38
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
bars1 = ax.bar([i - w/2 for i in x], [v*100 for v in RECALL5], width=w, label='Recall@5 (%)', color='#2563eb', zorder=3, edgecolor='white')
bars2 = ax.bar([i + w/2 for i in x], [v*100 for v in PREC5],  width=w, label='Precision@5 (%)', color='#f59e0b', zorder=3, edgecolor='white')
ax.set_xticks(x); ax.set_xticklabels(RAG_STRATEGIES, fontsize=11)
ax.set_ylabel('百分比 (%)', fontsize=12)
ax.set_title('RAG 消融实验 —— Recall@5 与 Precision@5 对比（N=38）', fontsize=14, pad=14, weight='bold')
ax.set_ylim(0, 110); ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
for b in bars1:
    ax.text(b.get_x()+b.get_width()/2, b.get_height()+1.2, f"{b.get_height():.1f}", ha='center', fontsize=9.5)
for b in bars2:
    ax.text(b.get_x()+b.get_width()/2, b.get_height()+1.2, f"{b.get_height():.1f}", ha='center', fontsize=9.5)
ax.legend(loc='upper right', fontsize=11); fig.tight_layout()
p1 = os.path.join(OUT_DIR, 'ablation_recall_precision.png')
fig.savefig(p1, bbox_inches='tight'); plt.close(fig); print('✅ 生成', p1)

# ========== 图 2: MRR / Hit@5 ==========
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
bars1 = ax.bar([i - w/2 for i in x], MRR,  width=w, label='MRR', color='#10b981', zorder=3, edgecolor='white')
bars2 = ax.bar([i + w/2 for i in x], [v*100 for v in HIT5], width=w, label='Hit@5 (%)', color='#7c3aed', zorder=3, edgecolor='white')
ax.set_xticks(x); ax.set_xticklabels(RAG_STRATEGIES, fontsize=11)
ax.set_title('RAG 消融实验 —— MRR 与 Hit@5 对比（N=38）', fontsize=14, pad=14, weight='bold')
ax.set_ylim(0, 115); ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
for b in bars1:
    ax.text(b.get_x()+b.get_width()/2, b.get_height()+1.2, f"{b.get_height():.3f}", ha='center', fontsize=9.5)
for b in bars2:
    ax.text(b.get_x()+b.get_width()/2, b.get_height()+1.2, f"{b.get_height():.1f}", ha='center', fontsize=9.5)
ax.legend(loc='upper right', fontsize=11); fig.tight_layout()
p2 = os.path.join(OUT_DIR, 'ablation_mrr_hit.png')
fig.savefig(p2, bbox_inches='tight'); plt.close(fig); print('✅ 生成', p2)

# ========== 图 3: SQL 三项指标 ==========
colors = ['#2563eb', '#10b981', '#f59e0b']
fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
bars = ax.bar(SQL_METRICS, [v*100 for v in SQL_VALUES], width=0.55, color=colors, zorder=3, edgecolor='white')
ax.set_ylabel('百分比 (%)', fontsize=12)
ax.set_title('Text-to-SQL 评估指标（N=32）', fontsize=14, pad=14, weight='bold')
ax.set_ylim(0, 115); ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
for b in bars:
    ax.text(b.get_x()+b.get_width()/2, b.get_height()+1.8, f"{b.get_height():.1f}%", ha='center', fontsize=12, weight='bold')
for tick, col in zip(ax.get_xticklabels(), colors):
    tick.set_color(col); tick.set_fontsize(12); tick.set_fontweight('bold')
fig.tight_layout()
p3 = os.path.join(OUT_DIR, 'sql_metrics.png')
fig.savefig(p3, bbox_inches='tight'); plt.close(fig); print('✅ 生成', p3)

print('\n🖼  所有图表已生成完毕：docs/')
for p in [p1, p2, p3]:
    print('  ·', os.path.basename(p))
