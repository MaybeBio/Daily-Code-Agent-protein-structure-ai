# 代码快照清单

- 上游仓库: https://github.com/M-Malek-Ht/clinvar-pathogenicity
- 快照日期: 2026-11-22
- 快照 commit: [`389dc38217dd`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/commit/389dc38217dd96e87168523fad1e525b73220be4)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (33 个文件, 1.0 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 17 | 1.0 MB |
| 文档 | 13 | 21.9 KB |
| README | 1 | 14.2 KB |
| 构建/配置 | 2 | 7.0 KB |

按后缀: `.ipynb` 2 (916.3 KB)、`.py` 15 (113.9 KB)、`.md` 13 (35.1 KB)、`.yml` 2 (7.0 KB)、`无后缀` 1 (1.1 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (37 个文件, 9.0 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 37 | 9.0 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`data/processed/variants.parquet`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/data/processed/variants.parquet) | 4.7 MB |
| [`data/splits/splits.parquet`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/data/splits/splits.parquet) | 1.6 MB |
| [`models/esm_esm2_t12_35M_UR50D_gbm_random_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/esm_esm2_t12_35M_UR50D_gbm_random_s0.joblib) | 716.7 KB |
| [`models/gbm_random_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/gbm_random_s0.joblib) | 710.6 KB |
| [`models/esm_esm2_t12_35M_UR50D_gbm_gene_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/esm_esm2_t12_35M_UR50D_gbm_gene_s0.joblib) | 191.7 KB |
| [`models/gbm_position_random_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/gbm_position_random_s0.joblib) | 189.7 KB |
| [`models/gbm_position_gene_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/gbm_position_gene_s0.joblib) | 189.7 KB |
| [`models/gbm_gene_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/gbm_gene_s0.joblib) | 185.6 KB |
| [`reports/figures/final_test_metrics.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/final_test_metrics.png) | 80.3 KB |
| [`reports/figures/final_test_calibration.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/final_test_calibration.png) | 65.5 KB |
| [`reports/figures/gbm_position_importance.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/gbm_position_importance.png) | 57.5 KB |
| [`reports/figures/baseline_calibration.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/baseline_calibration.png) | 55.4 KB |
| [`reports/figures/failure_slices.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/failure_slices.png) | 52.3 KB |
| [`reports/figures/final_random_vs_gene.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/final_random_vs_gene.png) | 52.2 KB |
| [`reports/figures/baseline_metrics.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/baseline_metrics.png) | 46.6 KB |
| [`reports/figures/abstention.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/abstention.png) | 45.9 KB |
| [`reports/figures/esm_llr_by_class.png`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/figures/esm_llr_by_class.png) | 32.6 KB |
| [`reports/failure_slices.csv`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/reports/failure_slices.csv) | 23.0 KB |
| [`models/esm_esm2_t12_35M_UR50D_lr_gene_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/esm_esm2_t12_35M_UR50D_lr_gene_s0.joblib) | 14.5 KB |
| [`models/esm_esm2_t12_35M_UR50D_lr_random_s0.joblib`](https://github.com/M-Malek-Ht/clinvar-pathogenicity/raw/HEAD/models/esm_esm2_t12_35M_UR50D_lr_random_s0.joblib) | 14.5 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
