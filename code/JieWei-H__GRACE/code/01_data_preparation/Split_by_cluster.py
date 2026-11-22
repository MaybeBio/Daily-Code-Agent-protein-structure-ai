import pickle
import random
import networkx as nx
from collections import defaultdict

random.seed(42)

# ============================================================
# 1. 加载数据
# ============================================================
with open('./complex_graphs.pkl', 'rb') as f:
    subgraphs = pickle.load(f)

print(f"总复合物数量: {len(subgraphs)}")

# ============================================================
# 2. 提取每个复合物的蛋白质集合
# ============================================================
def get_members(g):
    if isinstance(g, nx.Graph):
        return set(g.nodes())
    elif isinstance(g, (list, set, tuple)):
        return set(g)
    elif isinstance(g, dict):
        for k in ['nodes', 'members', 'proteins', 'genes']:
            if k in g:
                return set(g[k])
    raise TypeError(f"未识别的子图格式: {type(g)}")

member_sets = [get_members(g) for g in subgraphs]

# ============================================================
# 3. 按Jaccard相似度聚类
#    同一簇的复合物成员高度重叠，整体分到同一集合
#    阈值0.3：两个复合物共享超过30%成员则归为同簇
# ============================================================
print("开始聚类（Jaccard阈值=0.3）...")

n = len(subgraphs)
cluster_id = list(range(n))  # 初始每个复合物自成一簇

def find(x):
    while cluster_id[x] != x:
        cluster_id[x] = cluster_id[cluster_id[x]]
        x = cluster_id[x]
    return x

def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        cluster_id[rx] = ry

# 只遍历有公共蛋白的对（比全量O(n²)快）
protein_to_complexes = defaultdict(list)
for i, members in enumerate(member_sets):
    for p in members:
        protein_to_complexes[p].append(i)

checked = set()
merged = 0
for protein, complex_list in protein_to_complexes.items():
    for i in range(len(complex_list)):
        for j in range(i + 1, len(complex_list)):
            ci, cj = complex_list[i], complex_list[j]
            pair = (min(ci, cj), max(ci, cj))
            if pair in checked:
                continue
            checked.add(pair)
            s1, s2 = member_sets[ci], member_sets[cj]
            jaccard = len(s1 & s2) / len(s1 | s2)
            if jaccard >= 0.3:
                union(ci, cj)
                merged += 1

# 整理簇
clusters = defaultdict(list)
for i in range(n):
    clusters[find(i)].append(i)
cluster_list = list(clusters.values())

print(f"聚类完成，共 {len(cluster_list)} 个簇，合并了 {merged} 对")
print(f"单例簇数量: {sum(1 for c in cluster_list if len(c)==1)}")
print(f"最大簇大小: {max(len(c) for c in cluster_list)}")

# ============================================================
# 4. 按簇整体8:2分割
#    打乱簇顺序后按数量分配，保证8:2比例接近
# ============================================================
random.shuffle(cluster_list)

# 贪心分配：按复合物数量累积，达到20%截止
total = len(subgraphs)
target_test = int(total * 0.2)

test_indices = []
train_indices = []

for cluster in cluster_list:
    if len(test_indices) < target_test:
        test_indices.extend(cluster)
    else:
        train_indices.extend(cluster)

print(f"\n分割结果:")
print(f"  训练集复合物数: {len(train_indices)}")
print(f"  测试集复合物数: {len(test_indices)}")
print(f"  实际测试集比例: {len(test_indices)/total:.1%}")

# ============================================================
# 5. 统计蛋白质重叠情况
# ============================================================
train_proteins = set()
test_proteins  = set()

for i in train_indices:
    train_proteins.update(member_sets[i])
for i in test_indices:
    test_proteins.update(member_sets[i])

overlap = train_proteins & test_proteins
print(f"\n蛋白质重叠统计:")
print(f"  训练集蛋白数: {len(train_proteins)}")
print(f"  测试集蛋白数: {len(test_proteins)}")
print(f"  交集蛋白数:   {len(overlap)}")
print(f"  交集占测试集比例: {len(overlap)/len(test_proteins):.1%}  （原方案78.8%）")

# 统计完全unseen复合物
truly_unseen = []
for i in test_indices:
    if len(member_sets[i] & train_proteins) == 0:
        truly_unseen.append(i)
print(f"  完全unseen复合物数: {len(truly_unseen)}  （原方案43个）")
print(f"  占测试集比例: {len(truly_unseen)/len(test_indices):.1%}  （原方案5.6%）")

# ============================================================
# 6. 保存
# ============================================================
sft_train = [subgraphs[i] for i in train_indices]
sft_test  = [subgraphs[i] for i in test_indices]

with open('./Complex_Train.pkl', 'wb') as f:
    pickle.dump(sft_train, f)
with open('./Complex_Test.pkl', 'wb') as f:
    pickle.dump(sft_test, f)

# 同步保存蛋白质列表
train_protein_list = sorted(train_proteins)
test_protein_list  = sorted(test_proteins)

with open('./train_proteins.pkl', 'wb') as f:
    pickle.dump(train_protein_list, f)
with open('./test_proteins.pkl', 'wb') as f:
    pickle.dump(test_protein_list, f)


