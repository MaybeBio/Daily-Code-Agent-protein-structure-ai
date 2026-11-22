# 代码快照清单

- 上游仓库: https://github.com/Gleghorn-Lab/plm_interpretability
- 快照日期: 2026-11-22
- 快照 commit: [`77430ca997a6`](https://github.com/Gleghorn-Lab/plm_interpretability/commit/77430ca997a610600e1c32e93c5d21cb18c8309e)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (440 个文件, 5.2 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 365 | 4.7 MB |
| README | 27 | 270.7 KB |
| 文档 | 24 | 129.6 KB |
| 构建/配置 | 24 | 113.4 KB |

按后缀: `.py` 361 (4.6 MB)、`.md` 40 (323.0 KB)、`.toml` 1 (96.4 KB)、`无后缀` 11 (77.4 KB)、`.sh` 4 (19.4 KB)、`.txt` 19 (6.3 KB)、`.lock` 1 (4.6 KB)、`Dockerfile` 1 (4.0 KB)、`pyproject.toml` 1 (1.9 KB)、`.ini` 1 (216 B)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (34 个文件, 205.2 KB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 33 | 205.2 KB |
| 子模块未拉取 | 1 | 0 B |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`vendored/foundry/protein/matrices/evalue_nn.kerasify`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/foundry/protein/matrices/evalue_nn.kerasify) | 141.6 KB |
| [`vendored/foundry/embedding/profiles/embedding_profile_v1.json`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/foundry/embedding/profiles/embedding_profile_v1.json) | 30.0 KB |
| [`vendored/fastplms/LICENSES/e1/Apache-2.0.txt`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/LICENSES/e1/Apache-2.0.txt) | 11.1 KB |
| [`vendored/fastplms/LICENSES/e1/ATTRIBUTION`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/LICENSES/e1/ATTRIBUTION) | 6.8 KB |
| [`vendored/foundry/embedding/profiles/embedding_profile_v2.json`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/foundry/embedding/profiles/embedding_profile_v2.json) | 5.5 KB |
| [`vendored/foundry/embedding/profiles/embedding_profile_v3.json`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/foundry/embedding/profiles/embedding_profile_v3.json) | 5.4 KB |
| [`vendored/fastplms/LICENSES/e1/BSD-3-Clause.txt`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/LICENSES/e1/BSD-3-Clause.txt) | 1.5 KB |
| [`vendored/fastplms/requirements/features/oracles.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/oracles.in) | 523 B |
| [`scripts/exemplar_concepts.csv`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/scripts/exemplar_concepts.csv) | 322 B |
| [`vendored/fastplms/requirements/features/confidence.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/confidence.in) | 320 B |
| [`vendored/fastplms/requirements/features/dev.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/dev.in) | 220 B |
| [`vendored/fastplms/requirements/features/fp8.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/fp8.in) | 193 B |
| [`vendored/fastplms/requirements/profiles/candidate-structure.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/profiles/candidate-structure.in) | 190 B |
| [`vendored/fastplms/requirements/features/cueq.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/cueq.in) | 174 B |
| [`vendored/fastplms/requirements/features/structure.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/features/structure.in) | 149 B |
| [`vendored/fastplms/requirements/profiles/candidate.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/profiles/candidate.in) | 139 B |
| [`.gitignore`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/.gitignore) | 132 B |
| [`vendored/fastplms/requirements/core.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/core.in) | 121 B |
| [`vendored/fastplms/requirements/profiles/cpu-validation.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/profiles/cpu-validation.in) | 110 B |
| [`vendored/fastplms/requirements/profiles/artifact.in`](https://github.com/Gleghorn-Lab/plm_interpretability/raw/HEAD/vendored/fastplms/requirements/profiles/artifact.in) | 88 B |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
