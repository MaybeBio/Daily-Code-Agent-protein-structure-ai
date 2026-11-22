# 代码快照清单

- 上游仓库: https://github.com/qrefine/qrefine
- 快照日期: 2026-11-22
- 快照 commit: [`d88d57526149`](https://github.com/qrefine/qrefine/commit/d88d575261490b49fd1bd82451332cd898c50ade)
- 归档策略: `repo_copy=code` — **代码摘录,不是完整仓库**。保留源码、构建/配置文件、README、文档;数据、二进制、图片、权重不保留。

## 保留 (240 个文件, 2.0 MB)

| 类别 | 文件数 | 大小 |
|---|---:|---:|
| 源码 | 191 | 1.3 MB |
| 文档 | 34 | 629.9 KB |
| README | 6 | 20.9 KB |
| 构建/配置 | 9 | 7.6 KB |

按后缀: `.py` 174 (1.2 MB)、`.md` 38 (635.8 KB)、`.html` 11 (106.2 KB)、`.txt` 1 (11.1 KB)、`.css` 2 (9.5 KB)、`.sh` 3 (7.0 KB)、`.yaml` 8 (6.6 KB)、`无后缀` 1 (4.0 KB)、`Dockerfile` 1 (1.0 KB)、`.pbs` 1 (987 B)

> README / 文档中的相对图片与链接已改写为 GitHub 绝对地址。

## 省略 (427 个文件, 272.9 MB)

| 原因 | 文件数 | 大小 |
|---|---:|---:|
| 后缀不在白名单 | 427 | 272.9 MB |

体积最大的省略文件:

| 路径 | 大小 |
|---|---:|
| [`tests/regression/datasets/charmm/4p7h.pdb`](https://github.com/qrefine/qrefine/raw/HEAD/tests/regression/datasets/charmm/4p7h.pdb) | 4.4 MB |
| [`tests/regression/datasets/charmm/4fsx.pdb`](https://github.com/qrefine/qrefine/raw/HEAD/tests/regression/datasets/charmm/4fsx.pdb) | 3.4 MB |
| [`plugin/yoink/dat/np_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/np_lda.wfc) | 3.2 MB |
| [`plugin/yoink/dat/u__lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/u__lda.wfc) | 3.2 MB |
| [`plugin/yoink/dat/pa_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/pa_lda.wfc) | 3.2 MB |
| [`plugin/yoink/dat/pu_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/pu_lda.wfc) | 3.0 MB |
| [`plugin/yoink/dat/th_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/th_lda.wfc) | 3.0 MB |
| [`plugin/yoink/dat/ac_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/ac_lda.wfc) | 3.0 MB |
| [`plugin/yoink/dat/ra_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/ra_lda.wfc) | 2.8 MB |
| [`plugin/yoink/dat/fr_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/fr_lda.wfc) | 2.8 MB |
| [`plugin/yoink/dat/rn_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/rn_lda.wfc) | 2.6 MB |
| [`plugin/yoink/dat/at_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/at_lda.wfc) | 2.6 MB |
| [`plugin/yoink/dat/po_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/po_lda.wfc) | 2.6 MB |
| [`plugin/yoink/dat/bi_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/bi_lda.wfc) | 2.6 MB |
| [`plugin/yoink/dat/pb_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/pb_lda.wfc) | 2.6 MB |
| [`plugin/yoink/dat/tl_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/tl_lda.wfc) | 2.6 MB |
| [`tests/regression/datasets/charmm/3uj4.pdb`](https://github.com/qrefine/qrefine/raw/HEAD/tests/regression/datasets/charmm/3uj4.pdb) | 2.6 MB |
| [`tests/regression/datasets/charmm/4drw.psf`](https://github.com/qrefine/qrefine/raw/HEAD/tests/regression/datasets/charmm/4drw.psf) | 2.5 MB |
| [`plugin/yoink/dat/hg_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/hg_lda.wfc) | 2.5 MB |
| [`plugin/yoink/dat/au_lda.wfc`](https://github.com/qrefine/qrefine/raw/HEAD/plugin/yoink/dat/au_lda.wfc) | 2.5 MB |

> 省略规则:普通源码 >2 MB、文档/构建配置 >1 MB(README 与 .ipynb 不设限),或后缀不在白名单(图片/权重/数据表/二进制/通用 .txt/.log/.csv/.json/.xml 等)、以及子模块。需要全文时按上表链接直接取回,或用 git 克隆上游仓库。

> 本清单由 `scripts/archive.py` 每次归档时自动生成并覆盖。
