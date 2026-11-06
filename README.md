# JLC-R 最小代码闭包

当前实现：JLC-R-SOURCE-SPATIAL-20261106。入口 `code/simulation/jlc_r.py:JLCR`，默认拓扑加权源竞争 `spatial`。

仅保留 30 个传递依赖源码模块、一个运行入口、一个完整性核查入口、运行配置、依赖声明、源码哈希清单、许可和 Git 换行保持配置。18 个冻结父模块保持原字节。文件名包含历史编号的模块属于当前运行依赖，不是可删除的独立旧算法包。

仓库：https://github.com/mayanzu/JLC-R 。固定版本标签：`v2026.11.06-spatial`。

```powershell
git clone --branch v2026.11.06-spatial https://github.com/mayanzu/JLC-R.git
cd JLC-R
```

## 安装与核查

Python 3.12，在本目录执行：

```powershell
python -m pip install -r requirements.txt
python -B verify.py
python -B verify.py --smoke
```

普通核查仅验证闭包和哈希，自动忽略 Git 元数据及 Python 字节码缓存。`.gitattributes` 保持源文件原始字节，避免 Git 换行转换改变冻结模块哈希。`--smoke` 额外执行两轮合成输入检查，不写结果文件，不启动完整性能实验。

## 运行

```powershell
python -B run.py --seed 1320352547 --days 14 --supply 1.0 --output "../jlc-r-runs/example01"
```

输出目录必须全新且位于本代码包之外。默认使用合成天气；`--weather` 可传入外部 15 分钟 GHI CSV（表头之后第二列为非负 W/m² 数值，长度覆盖预热、运行和预测尾段）。实测数据和论文结果不随代码包保存。

`--source-protection` 默认为 `spatial`，显式匹配控制为 `unweighted`、`off`、`admission`、`headroom`；`priority` 和 `joint` 保留公共入口支持的另外两种显式模式。算法锁定 3 天预算、reference 触发与 relay_repair 内核。`config.json` 导出自主研究工作区的当前共享执行配置；没有沿用旧 RC2 目录的配置或实验身份。

本包执行算法，不包含论文数值复现所需的逐种子数据。完整论文与证据保存在主研究项目的版本化归档中。
