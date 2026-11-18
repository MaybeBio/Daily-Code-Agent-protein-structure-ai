# 代码快照清单

- 上游仓库: https://github.com/rcsb/foldmatch
- 快照日期: 2026-11-18
- 快照 commit: [`554acacace93`](https://github.com/rcsb/foldmatch/commit/554acacace931d8a8278b3869209b2169258e124)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (147 个文件, 3.7 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 139 | 3.1 MB |
| 构建/配置 | 5 | 478.2 KB |
| 文档 | 2 | 109.9 KB |
| README | 1 | 38.3 KB |

按后缀: `.py` 135 (3.1 MB)、`.lock` 1 (462.1 KB)、`.md` 3 (148.2 KB)、`.c` 2 (46.9 KB)、`.h` 2 (21.0 KB)、`.yaml` 2 (11.9 KB)、`Dockerfile` 1 (2.6 KB)、`pyproject.toml` 1 (1.7 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (29 个文件, 8.5 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 29 | 8.5 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`tests/resources/embeddings/1acb.A.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/embeddings/1acb.A.pt) | 1.4 MB |
| [`tests/resources/embeddings/2uzi.C.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/embeddings/2uzi.C.pt) | 1009.1 KB |
| [`tests/resources/esm_codes/fasta_rows_codes_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/fasta_rows_codes_v1.npz) | 892.9 KB |
| [`tests/resources/esm_codes/pairs_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/pairs_v1.npz) | 889.9 KB |
| [`tests/resources/esm_codes/encoder_rows_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/encoder_rows_v1.npz) | 841.2 KB |
| [`tests/resources/embeddings/2uzi.A.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/embeddings/2uzi.A.pt) | 697.1 KB |
| [`tests/resources/embeddings/2uzi.B.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/embeddings/2uzi.B.pt) | 637.1 KB |
| [`tests/resources/esm_codes/q90_queries_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/q90_queries_v1.npz) | 470.4 KB |
| [`tests/resources/pdb/2uzi.cif`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/pdb/2uzi.cif) | 418.3 KB |
| [`tests/resources/embeddings/1acb.B.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/embeddings/1acb.B.pt) | 391.1 KB |
| [`tests/resources/esm_codes/degenerate_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/degenerate_v1.npz) | 370.4 KB |
| [`tests/resources/pdb/1acb.cif`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/pdb/1acb.cif) | 286.5 KB |
| [`assets/embedding-model-architecture.png`](https://github.com/rcsb/foldmatch/raw/HEAD/assets/embedding-model-architecture.png) | 151.4 KB |
| [`tests/resources/esm_codes/evalue_grid_v1.json`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/evalue_grid_v1.json) | 70.0 KB |
| [`tests/resources/esm_codes/ood_rows_codes_v1.npz`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/ood_rows_codes_v1.npz) | 48.2 KB |
| [`tests/resources/esm_codes/FIXTURES.json`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/FIXTURES.json) | 28.5 KB |
| [`tests/resources/esm_codes/tokenizer_cases_v1.json`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/esm_codes/tokenizer_cases_v1.json) | 16.3 KB |
| [`tests/resources/alignment/mmseqs_comp_bias_pairs.tsv`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/alignment/mmseqs_comp_bias_pairs.tsv) | 14.3 KB |
| [`tests/resources/chain_embeddings/1acb.A.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/chain_embeddings/1acb.A.pt) | 7.5 KB |
| [`tests/resources/chain_embeddings/1acb.B.pt`](https://github.com/rcsb/foldmatch/raw/HEAD/tests/resources/chain_embeddings/1acb.B.pt) | 7.5 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
