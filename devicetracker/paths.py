"""应用路径。

集中在一处，避免用相对路径时被当前工作目录影响。
"""

from __future__ import annotations

import os
from pathlib import Path

# 本文件位于 devicetracker/ 内，上一级才是项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_ENV_VAR = "DEVICES_TRACKER_DB"


def default_db_path() -> Path:
    """返回数据库文件的绝对路径。

    默认放在项目根目录，方便备份和用 sqlite3 直接查看。设置环境变量
    ``DEVICES_TRACKER_DB`` 可以临时切到另一份数据（测试或试用时用）。

    这里必须返回绝对路径：``sqlite3.connect("devices.db")`` 是按**当前工作
    目录**解析的，从 PyCharm、终端、快捷方式启动会各自建出一个空库，
    看起来就像数据丢了。
    """
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "devices.db"
