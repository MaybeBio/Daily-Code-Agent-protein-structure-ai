# 代码快照清单

- 上游仓库: https://github.com/javierbq/rfd4-proteina-mlx
- 快照日期: 2026-11-22
- 快照 commit: [`290e475d56b2`](https://github.com/javierbq/rfd4-proteina-mlx/commit/290e475d56b2cb9234d470b232ec4d9a4e9f321f)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (100 个文件, 779.1 KB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 91 | 707.1 KB |
| 文档 | 8 | 68.0 KB |
| README | 1 | 4.1 KB |

按后缀: `.swift` 70 (602.1 KB)、`.py` 20 (102.3 KB)、`.md` 8 (70.0 KB)、`.sh` 1 (2.7 KB)、`无后缀` 1 (2.0 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (28 个文件, 24.7 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 28 | 24.7 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`Tests/RFD4MLXTests/Fixtures/conditioned.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/conditioned.json) | 5.6 MB |
| [`Tests/RFD4MLXTests/Fixtures/encoder.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/encoder.json) | 4.7 MB |
| [`Tests/RFD4MLXTests/Fixtures/binder.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/binder.json) | 4.0 MB |
| [`Tests/RFD4MLXTests/Fixtures/partialdiffusion.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/partialdiffusion.json) | 3.9 MB |
| [`Tests/RFD4MLXTests/Fixtures/predictsteps.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/predictsteps.json) | 1.8 MB |
| [`Tests/RFD4CoreTests/Fixtures/trunk.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4CoreTests/Fixtures/trunk.json) | 1.3 MB |
| [`Tests/RFD4MLXTests/Fixtures/bindernoise.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/bindernoise.json) | 1.3 MB |
| [`Tests/RFD4MLXTests/Fixtures/layer0.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/layer0.json) | 514.1 KB |
| [`Tests/RFD4MLXTests/Fixtures/matchednoise.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/matchednoise.json) | 348.7 KB |
| [`Tests/RFD4MLXTests/Fixtures/trunkio.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/trunkio.json) | 339.8 KB |
| [`Tests/RFD4MLXTests/Fixtures/trunkio_r4.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/trunkio_r4.json) | 339.8 KB |
| [`Tests/RFD4MLXTests/Fixtures/features.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/features.json) | 260.8 KB |
| [`Tests/RFD4CoreTests/Fixtures/structures/protein_binder_input.cif`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4CoreTests/Fixtures/structures/protein_binder_input.cif) | 165.3 KB |
| [`Tests/RFD4CoreTests/Fixtures/cif_reference.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4CoreTests/Fixtures/cif_reference.json) | 90.5 KB |
| [`Sources/RFD4Core/Resources/vocabulary.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Sources/RFD4Core/Resources/vocabulary.json) | 58.7 KB |
| [`Tests/RFD4MLXTests/Fixtures/decoderio.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/decoderio.json) | 53.9 KB |
| [`Tests/RFD4MLXTests/Fixtures/steps.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4MLXTests/Fixtures/steps.json) | 20.8 KB |
| [`Tests/RFD4CoreTests/Fixtures/schedules.json`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4CoreTests/Fixtures/schedules.json) | 16.2 KB |
| [`Tests/RFD4CoreTests/Fixtures/structures/enzyme_design_input.cif`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/Tests/RFD4CoreTests/Fixtures/structures/enzyme_design_input.cif) | 7.8 KB |
| [`validation/quality/fp16-vs-fp32-binder-structures.txt`](https://github.com/javierbq/rfd4-proteina-mlx/raw/HEAD/validation/quality/fp16-vs-fp32-binder-structures.txt) | 2.2 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
