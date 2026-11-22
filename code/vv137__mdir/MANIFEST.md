# 代码快照清单

- 上游仓库: https://github.com/vv137/mdir
- 快照日期: 2026-11-22
- 快照 commit: [`2c9ddc938eb1`](https://github.com/vv137/mdir/commit/2c9ddc938eb14bfba79726c05b10721aead02fb0)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (1569 个文件, 15.7 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 837 | 10.4 MB |
| 文档 | 639 | 5.1 MB |
| 构建/配置 | 73 | 126.4 KB |
| README | 20 | 117.3 KB |

按后缀: `.cpp` 241 (5.3 MB)、`.md` 655 (5.2 MB)、`.py` 393 (3.2 MB)、`.h` 150 (857.3 KB)、`.hpp` 1 (474.5 KB)、`.c` 9 (277.8 KB)、`.cu` 8 (187.8 KB)、`.sh` 33 (118.1 KB)、`CMakeLists.txt` 38 (50.9 KB)、`.toml` 23 (33.2 KB)、`.yml` 8 (19.5 KB)、`无后缀` 3 (13.2 KB)、`.lock` 2 (12.2 KB)、`Dockerfile` 1 (7.1 KB)、`pyproject.toml` 1 (3.5 KB)、`.cmake` 2 (2.9 KB)、`.tex` 1 (2.2 KB)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (1209 个文件, 9.0 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 1209 | 9.0 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`examples/ala3/ala3.prmtop`](https://github.com/vv137/mdir/raw/HEAD/examples/ala3/ala3.prmtop) | 797.7 KB |
| [`lib/Runtime/Templates/PMEGPU.mlir`](https://github.com/vv137/mdir/raw/HEAD/lib/Runtime/Templates/PMEGPU.mlir) | 448.0 KB |
| [`test/Driver/Inputs/ff19sb/ff19.prmtop`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/ff19sb/ff19.prmtop) | 406.8 KB |
| [`lib/Runtime/Templates/PMEGPUTriclinic.mlir`](https://github.com/vv137/mdir/raw/HEAD/lib/Runtime/Templates/PMEGPUTriclinic.mlir) | 312.1 KB |
| [`lib/Runtime/Templates/PMEGPUProlate.mlir`](https://github.com/vv137/mdir/raw/HEAD/lib/Runtime/Templates/PMEGPUProlate.mlir) | 275.4 KB |
| [`test/Driver/Inputs/opc/opc.prmtop`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/opc/opc.prmtop) | 264.0 KB |
| [`test/Driver/Inputs/fep/eth_wat.prmtop`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/fep/eth_wat.prmtop) | 230.0 KB |
| [`test/Driver/Inputs/dipeptide/dipeptide.prmtop`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/dipeptide/dipeptide.prmtop) | 198.4 KB |
| [`examples/ala3/ala3.inpcrd`](https://github.com/vv137/mdir/raw/HEAD/examples/ala3/ala3.inpcrd) | 174.9 KB |
| [`docs/paper/figures/energy-jac.png`](https://github.com/vv137/mdir/raw/HEAD/docs/paper/figures/energy-jac.png) | 149.1 KB |
| [`test/Driver/Inputs/kind-pairs/opc-795.loops`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/kind-pairs/opc-795.loops) | 110.6 KB |
| [`scripts/experiments/neighbor-structures/results/search.png`](https://github.com/vv137/mdir/raw/HEAD/scripts/experiments/neighbor-structures/results/search.png) | 97.9 KB |
| [`docs/paper/figures/suite.png`](https://github.com/vv137/mdir/raw/HEAD/docs/paper/figures/suite.png) | 96.5 KB |
| [`test/Driver/Inputs/kind-pairs/tip3p-795.loops`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/kind-pairs/tip3p-795.loops) | 96.0 KB |
| [`lib/Runtime/Templates/PME.mlir`](https://github.com/vv137/mdir/raw/HEAD/lib/Runtime/Templates/PME.mlir) | 95.2 KB |
| [`test/Driver/Inputs/gb/peptide.prmtop`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/gb/peptide.prmtop) | 91.6 KB |
| [`scripts/experiments/neighbor-structures/results/pairs.png`](https://github.com/vv137/mdir/raw/HEAD/scripts/experiments/neighbor-structures/results/pairs.png) | 89.4 KB |
| [`test/Driver/Inputs/ff19sb/ff19.inpcrd`](https://github.com/vv137/mdir/raw/HEAD/test/Driver/Inputs/ff19sb/ff19.inpcrd) | 83.2 KB |
| [`scripts/experiments/neighbor-structures/results/scan.png`](https://github.com/vv137/mdir/raw/HEAD/scripts/experiments/neighbor-structures/results/scan.png) | 81.5 KB |
| [`include/mdir/Dialect/MDExec/MDExecOps.td`](https://github.com/vv137/mdir/raw/HEAD/include/mdir/Dialect/MDExec/MDExecOps.td) | 77.4 KB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
