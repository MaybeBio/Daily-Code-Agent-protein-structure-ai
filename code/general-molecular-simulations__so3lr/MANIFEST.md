# 代码快照清单

- 上游仓库: https://github.com/general-molecular-simulations/so3lr
- 快照日期: 2026-11-22
- 快照 commit: [`889abc332ec3`](https://github.com/general-molecular-simulations/so3lr/commit/889abc332ec3e15fc4cf07c4801faaa01c0367f5)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (247 个文件, 3.4 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 213 | 2.8 MB |
| 构建/配置 | 26 | 588.7 KB |
| README | 4 | 14.7 KB |
| 文档 | 4 | 12.5 KB |

按后缀: `.py` 202 (2.6 MB)、`.lock` 1 (427.4 KB)、`.yaml` 21 (99.6 KB)、`.cu` 3 (76.8 KB)、`.ipynb` 5 (75.9 KB)、`setup.py` 1 (43.5 KB)、`.md` 7 (26.1 KB)、`.yml` 2 (12.6 KB)、`.cuh` 2 (11.6 KB)、`pyproject.toml` 1 (5.7 KB)、`.sh` 1 (1.2 KB)、`无后缀` 1 (1.1 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (60 个文件, 31.5 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 60 | 31.5 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`so3lr/models/so3lr-tauri-l-2602/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-l-2602/params.pkl) | 6.8 MB |
| [`so3lr/models/so3lr-tauri-l-2606/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-l-2606/params.pkl) | 6.8 MB |
| [`examples/data/sapt10k.zip`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/examples/data/sapt10k.zip) | 3.2 MB |
| [`so3lr/models/so3lr-tauri-m-2602/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-m-2602/params.pkl) | 2.0 MB |
| [`so3lr/models/so3lr-tauri-m-2606/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-m-2606/params.pkl) | 2.0 MB |
| [`so3lr/models/so3lr/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr/params.pkl) | 2.0 MB |
| [`so3lr/models/so3lr-tauri-s-2602/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-s-2602/params.pkl) | 1.6 MB |
| [`so3lr/models/so3lr-tauri-s-2606/params.pkl`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/models/so3lr-tauri-s-2606/params.pkl) | 1.6 MB |
| [`tests/mlff_tests/test_data/data_set_pbc.xyz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/mlff_tests/test_data/data_set_pbc.xyz) | 991.4 KB |
| [`examples/data/ethanol.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/examples/data/ethanol.npz) | 877.9 KB |
| [`tests/mlff_tests/test_data/ethanol.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/mlff_tests/test_data/ethanol.npz) | 877.9 KB |
| [`so3lr/logo.png`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/logo.png) | 676.5 KB |
| [`tests/test_data/ac.xyz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/test_data/ac.xyz) | 519.5 KB |
| [`tests/mlff_tests/test_data/data_set_pbc.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/mlff_tests/test_data/data_set_pbc.npz) | 306.3 KB |
| [`tests/test_data/water_pbc_dummy.xyz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/test_data/water_pbc_dummy.xyz) | 218.2 KB |
| [`tests/mlff_tests/test_data/data_set.xyz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/mlff_tests/test_data/data_set.xyz) | 207.9 KB |
| [`so3lr/mlff/nn/observable/nlh_ref.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/mlff/nn/observable/nlh_ref.npz) | 196.6 KB |
| [`so3lr/mlff/utils/robust_loss_jax/data/partition_spline.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/so3lr/mlff/utils/robust_loss_jax/data/partition_spline.npz) | 192.6 KB |
| [`tests/test_data/water_1536.xyz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/test_data/water_1536.xyz) | 157.6 KB |
| [`tests/test_data/water_ase.npz`](https://github.com/general-molecular-simulations/so3lr/raw/HEAD/tests/test_data/water_ase.npz) | 36.5 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
