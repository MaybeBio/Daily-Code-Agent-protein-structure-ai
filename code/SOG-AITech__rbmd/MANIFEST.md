# 代码快照清单

- 上游仓库: https://github.com/SOG-AITech/rbmd
- 快照日期: 2026-11-22
- 快照 commit: [`9690c12a7f50`](https://github.com/SOG-AITech/rbmd/commit/9690c12a7f506953f2d813556404dcd1f950cf89)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (372 个文件, 3.5 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 339 | 3.4 MB |
| 文档 | 7 | 92.7 KB |
| README | 15 | 43.8 KB |
| 构建/配置 | 11 | 25.1 KB |

按后缀: `.cpp` 92 (1.2 MB)、`.hpp` 10 (1015.1 KB)、`.cu` 23 (543.8 KB)、`.h` 149 (359.4 KB)、`.py` 35 (181.9 KB)、`.md` 20 (100.8 KB)、`无后缀` 1 (34.3 KB)、`.sh` 15 (27.2 KB)、`CMakeLists.txt` 10 (15.8 KB)、`.cmake` 7 (14.7 KB)、`.slurm` 8 (12.5 KB)、`.yml` 1 (9.4 KB)、`.rst` 1 (1.4 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (44 个文件, 14.2 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 44 | 14.2 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`examples/01-peo/peo+Li.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/01-peo/peo%2BLi.data) | 6.9 MB |
| [`examples/02-water-methane/H2O-CH4.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/02-water-methane/H2O-CH4.data) | 3.2 MB |
| [`examples/02-water-methane/methane-hydrate/TIP3P-CH4_supercell_4_v.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/02-water-methane/methane-hydrate/TIP3P-CH4_supercell_4_v.data) | 1.7 MB |
| [`examples/03-metal/Au/Au_4k_v.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Au/Au_4k_v.data) | 514.9 KB |
| [`examples/03-metal/Ag/Ag_4k_v.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Ag/Ag_4k_v.data) | 513.5 KB |
| [`examples/03-metal/Cu/Cu10_v.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Cu/Cu10_v.data) | 512.6 KB |
| [`tools/spdlog-1.14.1.tar.gz`](https://github.com/SOG-AITech/rbmd/raw/HEAD/tools/spdlog-1.14.1.tar.gz) | 264.5 KB |
| [`tools/ftxui-6.1.9.tar.gz`](https://github.com/SOG-AITech/rbmd/raw/HEAD/tools/ftxui-6.1.9.tar.gz) | 256.8 KB |
| [`tools/cxxopts-3.1.1.tar.gz`](https://github.com/SOG-AITech/rbmd/raw/HEAD/tools/cxxopts-3.1.1.tar.gz) | 99.2 KB |
| [`examples/04-threebody/BNC/hBN-monolayer-5nm_v0.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/04-threebody/BNC/hBN-monolayer-5nm_v0.data) | 92.2 KB |
| [`benchmark/05_timing_scaling/matrix.json`](https://github.com/SOG-AITech/rbmd/raw/HEAD/benchmark/05_timing_scaling/matrix.json) | 65.4 KB |
| [`examples/04-threebody/Si/Si_v0.data`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/04-threebody/Si/Si_v0.data) | 64.4 KB |
| [`examples/03-metal/Cu/Cu_u3.eam`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Cu/Cu_u3.eam) | 35.7 KB |
| [`examples/03-metal/Ag/Ag_u3.eam`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Ag/Ag_u3.eam) | 35.7 KB |
| [`examples/03-metal/Au/Au_u3.eam`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/03-metal/Au/Au_u3.eam) | 35.7 KB |
| [`LICENSES/nlohmann-json-3.12.0/Apache-2.0.txt`](https://github.com/SOG-AITech/rbmd/raw/HEAD/LICENSES/nlohmann-json-3.12.0/Apache-2.0.txt) | 10.0 KB |
| [`.clang-format`](https://github.com/SOG-AITech/rbmd/raw/HEAD/.clang-format) | 7.3 KB |
| [`LICENSES/nlohmann-json-3.12.0/CC0-1.0.txt`](https://github.com/SOG-AITech/rbmd/raw/HEAD/LICENSES/nlohmann-json-3.12.0/CC0-1.0.txt) | 6.9 KB |
| [`benchmark/SHA256SUMS`](https://github.com/SOG-AITech/rbmd/raw/HEAD/benchmark/SHA256SUMS) | 6.2 KB |
| [`examples/04-threebody/BNC/BNC.tersoff`](https://github.com/SOG-AITech/rbmd/raw/HEAD/examples/04-threebody/BNC/BNC.tersoff) | 5.5 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
