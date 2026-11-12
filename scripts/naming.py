"""茶馆杂谈 JM 系列命名规则（唯一事实源）。

新格式：``YY.MM月-JM<编号>-<文章名>``，无编号时为 ``YY.MM月-JM早期文章-<文章名>``。
例：``25.07月-JM918-我们就是聪明一些`` / ``18.06月-JM早期文章-欢迎回家20210925``

用途：
- 同步时由 ``sync.py`` / ``archive_pdfs.py`` 生成新文件名；
- 历史回刷时由一次性迁移脚本解析旧名并转换。

约定：
- 只处理文件名（stem），不含扩展名；
- 标题保留原文，仅去首尾空白与文件系统非法字符（`\\ / : * ? " < > |`）；
- 已是新格式的名字再解析应保持不变（幂等）。
"""

import re
from typing import Optional

EARLY_TAG = "JM早期文章"

_NEW_RE = re.compile(r"^(\d{2})\.(\d{2})月-(JM\d+|" + EARLY_TAG + r")-(.+)$")
_YM_PREFIX_RE = re.compile(r"^(\d{4})年(\d{2})月_(.+)$")
_JM_PREFIX_RE = re.compile(r"^JM\s*[:：]?\s*(\d+)\s*(.*)$", re.IGNORECASE)
_TRAIL_DATE_RE = re.compile(r"(\d{4})(\d{2})\d{2}$")
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|]')

# 非 JM 系列（不进茶馆杂谈，但仍归档项目资料库）
_NON_JM_RE = re.compile(r"^(python学习材料|ptyhon学习材料|外篇|WP)\s*\d+")


def sanitize_title(title: str) -> str:
    """清掉文件系统非法字符，保留连字符（它是命名分隔符）。"""
    return _ILLEGAL_RE.sub("", title).strip()


def build_stem(year: int, month: int, jm_num: Optional[int], title: str) -> str:
    """按新规则拼文件名（不含扩展名）。"""
    if not 1 <= month <= 12:
        raise ValueError(f"月份非法: {month}")
    tag = f"JM{jm_num}" if jm_num is not None else EARLY_TAG
    clean = sanitize_title(title) or "未命名"
    return f"{year % 100:02d}.{month:02d}月-{tag}-{clean}"


def is_new_style(stem: str) -> bool:
    return bool(_NEW_RE.match(stem))


def year_of(stem: str) -> Optional[int]:
    """新命名 ``YY.MM月-...`` 的完整年份；非新格式返回 None。"""
    m = _NEW_RE.match(stem)
    return 2000 + int(m.group(1)) if m else None


def month_of(stem: str) -> Optional[int]:
    m = _NEW_RE.match(stem)
    return int(m.group(2)) if m else None


def is_non_jm(name: str) -> bool:
    """python / 外篇 / WP 系列：不进茶馆杂谈。"""
    return bool(_NON_JM_RE.match(name))


def extract_jm_num(name: str) -> Optional[int]:
    """从新旧两种命名中取 JM 编号；无编号（早期文章）返回 None。"""
    m = _JM_PREFIX_RE.match(name) or re.search(r"-JM(\d+)-", name)
    return int(m.group(1)) if m else None


def is_early_article(name: str) -> bool:
    return bool(re.search(r"-" + EARLY_TAG + r"-", name))


def is_jm_series(stem: str) -> bool:
    """是否 JM 系列（含无编号的早期文章）。python / 外篇 / WP 不算。

    同时认三种写法：
    - 新命名 ``YY.MM月-JM123-标题`` / ``YY.MM月-JM早期文章-标题``
    - 中间态 ``2021年01月_JM123 标题``
    - 下载产物原名 ``JM123 标题``（旧名）
    """
    if is_non_jm(stem):
        return False
    if _NEW_RE.match(stem):
        return True
    m = _YM_PREFIX_RE.match(stem)
    if m:
        rest = m.group(3)
        return bool(_JM_PREFIX_RE.match(rest)) or rest.startswith(EARLY_TAG)
    return bool(_JM_PREFIX_RE.match(stem))


def parse_legacy(stem: str) -> Optional[dict]:
    """解析旧命名，返回 {year, month, jm_num, title, source}。

    - year/month 可能为 None（纯 ``JMxxxx 标题`` 需要外部补年月）；
    - 无法识别返回 None（调用方决定跳过/报错）。
    """
    m = _NEW_RE.match(stem)
    if m:
        return {
            "year": 2000 + int(m.group(1)),
            "month": int(m.group(2)),
            "jm_num": None if m.group(3) == EARLY_TAG else int(m.group(3)[2:]),
            "title": m.group(4),
            "source": "已是新格式",
        }

    m = _YM_PREFIX_RE.match(stem)
    if m:
        year, month, rest = int(m.group(1)), int(m.group(2)), m.group(3)
        j = _JM_PREFIX_RE.match(rest)
        return {
            "year": year,
            "month": month,
            "jm_num": int(j.group(1)) if j else None,
            "title": (j.group(2) if j else rest).lstrip("-_ ").strip(),
            "source": "文件名年月",
        }

    j = _JM_PREFIX_RE.match(stem)
    if j:
        return {
            "year": None,
            "month": None,
            "jm_num": int(j.group(1)),
            "title": j.group(2).strip(),
            "source": "待补年月",
        }

    m = _TRAIL_DATE_RE.search(stem)
    if m and 1 <= int(m.group(2)) <= 12:
        return {
            "year": int(m.group(1)),
            "month": int(m.group(2)),
            "jm_num": None,
            "title": stem,
            "source": "标题尾日期",
        }

    return None


def build_from_entry(title_stem: str, entry_index: str, sync_year: int,
                     sync_month: Optional[int] = None) -> str:
    """同步时用：从下载产物 stem + 条目 ``MMDD更新`` 生成新文件名。

    title_stem 形如 ``JM1140 小弟与帮派``（下载产物的 stem）；
    entry_index 形如 ``1025更新``，取 4 位月日。
    sync_month 省略时取当前月；条目月比同步月大 2 个月以上视为上一年
    （例：1 月同步 12 月条目）。
    """
    digits = re.match(r"^(\d{4})", entry_index)
    if not digits:
        raise ValueError(f"条目日期非法: {entry_index}")
    month = int(digits.group(1)[:2])
    if not 1 <= month <= 12:
        raise ValueError(f"条目月份非法: {entry_index}")

    if sync_month is None:
        from datetime import datetime
        sync_month = datetime.now().month

    year = sync_year - 1 if month > sync_month + 1 else sync_year

    parsed = parse_legacy(title_stem)
    if not parsed:
        raise ValueError(f"无法解析下载产物名: {title_stem}")

    return build_stem(year, month, parsed["jm_num"], parsed["title"] or title_stem)
