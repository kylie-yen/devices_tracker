# 设备持有成本跟踪

记录电子产品的购入价格、持有时间、日均价格和折旧售出价格的桌面小工具。

## 它能算什么

每台设备记录四个事实：购入价、购入日期、售出价、售出日期。其余都是读的时候现算的：

| 指标 | 算法 |
| --- | --- |
| 持有天数 | 已售出：售出日 − 购入日；持有中：今天 − 购入日 |
| 购入成本日均 | 购入价 ÷ 持有天数 |
| 净成本日均 | (购入价 − 售出价) ÷ 持有天数，未售出时售出价按 0 计 |

两个日均口径都显示。**净成本日均**才是「这东西一天到底花了我多少钱」的答案：
卖掉之后这个数字会大幅下降。如果卖价高于买价，它会变成负数（绿色显示），
表示这件设备不但没花钱还赚了。

两个约定值得知道：

- **持有不足一天按一天计。** 当天买当天卖时持有天数是 0，直接做分母会除零；
  约定分母最小为 1，语义上也说得通（持有 1 天的日均本来就等于全价）。
- **未售出的判定看售出日期，不看售出价。** 所以「送人 / 丢失，售价 0」会被正确
  记成已售出，而不是持有中。

## 功能

- 添加 / 编辑 / 删除设备记录
- 汇总统计面板：总投入、已回血、净支出、两个口径的日均合计
- 按关键词（名称 / 分类 / 备注）搜索，按分类和持有状态筛选
- 导出 CSV / Excel（默认导出当前筛选后的视图，与屏幕顺序一致）
- 跨零点自动刷新持有天数和日均价格

## 安装与运行

```bash
pip install -r requirements.txt
python main.py
```

也可以 `python -m devicetracker`。

## 数据存放在哪

SQLite 数据库默认是项目根目录下的 `devices.db`，已被 `.gitignore` 忽略。
想换一份数据（试用、测试）就设环境变量：

```bash
DEVICES_TRACKER_DB=D:/备份/devices.db python main.py
```

路径由 [devicetracker/paths.py](devicetracker/paths.py) 统一推导成绝对路径。
**不要**在代码里写 `sqlite3.connect("devices.db")` —— 那是按当前工作目录解析的，
从 PyCharm、终端、快捷方式启动会各自建出一个空库，看起来就像数据丢了。

## 代码结构

```
main.py                     入口
devicetracker/
├── app.py                  装配 QApplication 与主窗口
├── paths.py                数据库路径（绝对路径，唯一来源）
├── models.py               Device、派生计算、筛选谓词 —— 不依赖 Qt
├── database.py             SQLite schema 与增删改查
├── exporter.py             CSV / Excel 导出
└── ui/
    ├── table_model.py      表格模型 + 筛选排序代理
    ├── device_dialog.py    添加 / 编辑对话框
    └── main_window.py      窗口组装
tests/                      pytest 单元测试
```

分层约定：**UI 层不做计算，纯计算不 import Qt**。`models.py` 里的持有天数、
日均价格、筛选规则全部是可注入 `today` 的纯函数，所以业务规则能在没有
QApplication 的环境下秒测，UI 怎么改都不影响这层。

## 开发

```bash
python -m pytest
```

单元测试覆盖派生计算的全部边界（当天买卖、未来日期、售出早于购入、售价高于
购入价、价格为零、送人售价为零）、数据库往返与约束、以及导出编码和数字格式。
UI 层不写单元测试 —— 筛选判定已经抽成纯函数 `models.matches()`，代理那边只剩
一行委托。

## 已知的坑（改代码前先看）

- **`QDoubleSpinBox` 默认上限只有 99.99。** 必须显式 `setRange()`，否则用户输入
  5999 会被静默截断成 99.99，然后以为程序算错了。
- **表格排序必须走 `SORT_ROLE`。** `DisplayRole` 返回的是 `"¥1,234.56"`，拿它排序
  会变成字符串比较，`"9.5" > "10.2"`。代理用 `setSortRole(SORT_ROLE)` 拿原始数值。
- **日期必须显式转 ISO 字符串再进数据库。** Python 3.12 起 sqlite3 的隐式 `date`
  适配器已弃用，直接传 `date` 对象会收到 `DeprecationWarning`。
- **模型 / 代理 / 数据库对象要存成实例属性。** 写成局部变量的话，Python 回收对象后
  底层 C++ 对象被销毁，表格会空白甚至崩溃。
- **`QAction` 在 PyQt6 里来自 `QtGui`，不是 `QtWidgets`。** 所有枚举都是作用域枚举
  （`Qt.ItemDataRole.DisplayRole` 而不是 `Qt.DisplayRole`），`exec_()` 已删除。
