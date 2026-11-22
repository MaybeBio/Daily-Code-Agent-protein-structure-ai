# 代码快照清单

- 上游仓库: https://github.com/aqlaboratory/openfold
- 快照日期: 2026-11-22
- 快照 commit: [`be2ec1841f16`](https://github.com/aqlaboratory/openfold/commit/be2ec1841f16c966c65ae0e7599ebbadc725757d)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (195 个文件, 1.6 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 171 | 1.4 MB |
| 文档 | 13 | 103.6 KB |
| 构建/配置 | 10 | 9.3 KB |
| README | 1 | 2.9 KB |

按后缀: `.py` 135 (1.4 MB)、`.md` 13 (95.5 KB)、`.ipynb` 1 (45.2 KB)、`.sh` 31 (40.6 KB)、`无后缀` 1 (11.1 KB)、`.cu` 1 (6.9 KB)、`setup.py` 1 (4.6 KB)、`.cpp` 2 (2.3 KB)、`.yml` 6 (2.0 KB)、`Dockerfile` 1 (1.8 KB)、`Makefile` 1 (638 B)、`.yaml` 1 (287 B)、`.h` 1 (215 B)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (40 个文件, 67.4 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 40 | 67.4 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`tests/test_data/alignments/2q2k_A/hmm_output.sto`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/alignments/2q2k_A/hmm_output.sto) | 19.5 MB |
| [`tests/test_data/alignments/2q2k_B/hmm_output.sto`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/alignments/2q2k_B/hmm_output.sto) | 19.5 MB |
| [`tests/test_data/mmcifs/1hf9.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/1hf9.cif) | 4.1 MB |
| [`examples/monomer/alignments/6KWC_1/uniref90_hits.sto`](https://github.com/aqlaboratory/openfold/raw/HEAD/examples/monomer/alignments/6KWC_1/uniref90_hits.sto) | 4.1 MB |
| [`tests/test_data/sample_feats.pickle.gz`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/sample_feats.pickle.gz) | 3.9 MB |
| [`tests/test_data/features.pkl`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/features.pkl) | 3.7 MB |
| [`tests/test_data/mmcifs/2crb.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/2crb.cif) | 2.6 MB |
| [`examples/monomer/alignments/6KWC_1/mgnify_hits.sto`](https://github.com/aqlaboratory/openfold/raw/HEAD/examples/monomer/alignments/6KWC_1/mgnify_hits.sto) | 1.9 MB |
| [`docs/imgs/of_banner.png`](https://github.com/aqlaboratory/openfold/raw/HEAD/docs/imgs/of_banner.png) | 1.8 MB |
| [`imgs/of_banner.png`](https://github.com/aqlaboratory/openfold/raw/HEAD/imgs/of_banner.png) | 1.8 MB |
| [`tests/test_data/alphafold_feature_dict.pickle`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/alphafold_feature_dict.pickle) | 1.0 MB |
| [`tests/test_data/mmcifs/1psm.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/1psm.cif) | 971.2 KB |
| [`tests/test_data/mmcifs/5kc1.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/5kc1.cif) | 645.8 KB |
| [`examples/monomer/alignments/6KWC_1/bfd_uniref_hits.a3m`](https://github.com/aqlaboratory/openfold/raw/HEAD/examples/monomer/alignments/6KWC_1/bfd_uniref_hits.a3m) | 382.4 KB |
| [`tests/test_data/mmcifs/3u8v.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/3u8v.cif) | 262.0 KB |
| [`examples/monomer/sample_predictions/6KWC_1_model_1_ptm_relaxed.pdb`](https://github.com/aqlaboratory/openfold/raw/HEAD/examples/monomer/sample_predictions/6KWC_1_model_1_ptm_relaxed.pdb) | 224.8 KB |
| [`tests/test_data/mmcifs/4zey.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/4zey.cif) | 178.0 KB |
| [`tests/test_data/mmcifs/2q2k.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/2q2k.cif) | 163.4 KB |
| [`tests/test_data/mmcifs/4i6p.cif`](https://github.com/aqlaboratory/openfold/raw/HEAD/tests/test_data/mmcifs/4i6p.cif) | 156.4 KB |
| [`examples/monomer/alignments/6KWC_1/hhsearch_output.hhr`](https://github.com/aqlaboratory/openfold/raw/HEAD/examples/monomer/alignments/6KWC_1/hhsearch_output.hhr) | 133.0 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
