# 代码快照清单

- 上游仓库: https://github.com/DannyJPark/ChIEDiff
- 快照日期: 2026-11-22
- 快照 commit: [`8f9a2dd3a4ee`](https://github.com/DannyJPark/ChIEDiff/commit/8f9a2dd3a4eece0ff998932c502244c3895c3eff)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (65 个文件, 512.7 KB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 50 | 460.3 KB |
| 构建/配置 | 8 | 24.7 KB |
| 文档 | 3 | 13.9 KB |
| README | 4 | 13.9 KB |

按后缀: `.py` 47 (407.0 KB)、`.ipynb` 1 (42.0 KB)、`.md` 6 (26.5 KB)、`.yml` 6 (20.5 KB)、`.sh` 2 (11.2 KB)、`pyproject.toml` 1 (2.8 KB)、`Makefile` 1 (1.4 KB)、`无后缀` 1 (1.3 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (30 个文件, 8.3 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 30 | 8.3 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`gated_energy_diffusion/utils/evaluation/fpscores.pkl.gz`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/gated_energy_diffusion/utils/evaluation/fpscores.pkl.gz) | 3.7 MB |
| [`results/comparison/f4_delta_score/delta_score_per_mol.csv.gz`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/f4_delta_score/delta_score_per_mol.csv.gz) | 2.8 MB |
| [`docs/assets/sampling_trajectory.gif`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/docs/assets/sampling_trajectory.gif) | 1.2 MB |
| [`data/crossdocked_pocket10_pose_split.pt`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/data/crossdocked_pocket10_pose_split.pt) | 415.2 KB |
| [`results/diagnostics/type_cf/pocket0.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/type_cf/pocket0.csv) | 34.1 KB |
| [`results/diagnostics/type_cf/pocket4.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/type_cf/pocket4.csv) | 34.1 KB |
| [`results/diagnostics/type_cf/pocket1.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/type_cf/pocket1.csv) | 34.0 KB |
| [`results/diagnostics/type_cf/pocket3.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/type_cf/pocket3.csv) | 33.9 KB |
| [`results/diagnostics/type_cf/pocket2.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/type_cf/pocket2.csv) | 33.7 KB |
| [`results/comparison/master_table.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/master_table.csv) | 6.6 KB |
| [`data/test_pocket_order.json`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/data/test_pocket_order.json) | 6.1 KB |
| [`results/diagnostics/ablation_nci_v2/posecheck_ablation_all.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/ablation_nci_v2/posecheck_ablation_all.csv) | 4.5 KB |
| [`results/comparison/appendix/posebusters/pose_quality_summary_posebusters.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/appendix/posebusters/pose_quality_summary_posebusters.csv) | 3.6 KB |
| [`results/comparison/f1_sbdd/properties/property_overall.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/f1_sbdd/properties/property_overall.csv) | 3.6 KB |
| [`results/comparison/f1_sbdd/bond_jsd/bond_jsd_overall.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/f1_sbdd/bond_jsd/bond_jsd_overall.csv) | 3.3 KB |
| [`results/comparison/f1_sbdd/main_table/main_table.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/f1_sbdd/main_table/main_table.csv) | 3.2 KB |
| [`results/diagnostics/ablation_nci/nci_summary_abl.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/ablation_nci/nci_summary_abl.csv) | 3.0 KB |
| [`results/diagnostics/ablation_nci_v2/dock_success.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/diagnostics/ablation_nci_v2/dock_success.csv) | 2.8 KB |
| [`results/MANIFEST.sha256`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/MANIFEST.sha256) | 2.5 KB |
| [`results/comparison/f1_sbdd/ring_size/ring_size_overall.csv`](https://github.com/DannyJPark/ChIEDiff/raw/HEAD/results/comparison/f1_sbdd/ring_size/ring_size_overall.csv) | 2.2 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
