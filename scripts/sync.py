"""
茶馆系列文件同步 - 一键同步主控脚本

用法：
    cd scripts
    python3 sync.py              # 默认从上次同步时点继续
    python3 sync.py 0331         # 手动指定上次同步日期（首次运行）
    python3 sync.py --headless   # 后台运行（不显示浏览器窗口）

流程（步骤编号与运行时 log 一致）：
    1. 抓取坚果云页面（含密码重试 + 封禁保护）
    2. 解析 HTML 提取所有条目
    3. 从上次同步日期（最后一列最新位置）开始下载
    4. 解压压缩包
    5. 处理 .exe 伪装 PDF 文件
    6. PDF → Markdown 转换（含图片检测和双引擎质检；仅 JM 系列，
       python/外篇/WP 只下载+归档，不转 MD）
    7. 归档 PDF（只进项目资料库，知识库只放 MD）：
       JM -> 周老师茶馆历史文档/历史学习资料-YYYY（按发布年，<=2020 进 2020及以前），
       python/外篇/WP -> 周老师茶馆历史文档/Python学习材料
    8. 更新 progress.json
    9. 完整性验证（检查 last_date~latest_date 范围内每个条目状态 + JM/WP/python 序列断号）

注：本机没有 `python` 命令，一律用 `python3`。
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# 导入 PDF 转换器
sys.path.insert(0, str(Path(__file__).parent))
from pdf_to_md import PdfConverter, auto_detect_mode
from naming import (build_from_entry, build_stem, parse_legacy, extract_jm_num,
                    is_jm_series)
from archive_pdfs import archive_pdfs  # 归档：PDF 只进项目资料库（知识库只放 MD）

# ── 配置（Mac 本地适配）──────────────────────────────────
PROJECT_ROOT    = Path(__file__).parent.parent
PROGRESS_FILE   = PROJECT_ROOT / "progress.json"
SOURCE_FILE     = Path.home() / "Downloads" / "特殊秘籍20240405.txt"
DOWNLOAD_DIR    = Path("/Users/allenwywang/allen个人项目/project-zhou/茶馆杂谈文件同步")
# 历史学习知识库（独立 Obsidian 库，与 project-zhou 同级目录；
# 2026-11-06 从 周老师茶馆历史文档/历史学习资料项目/ 迁出到这个位置）
HISTORY_KB_ROOT = PROJECT_ROOT.parent / "历史学习资料"
MARKDOWN_DIR    = HISTORY_KB_ROOT / "历史学习" / "raw" / "articles" / "茶馆杂谈"
LANZOU_BASE_URL = "https://lanzoui.com/"
SEVENZIP        = "7z"  # Homebrew p7zip 安装后的命令
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
# 单次点击后等待 download 事件的时长。蓝奏云部分链接点击后会打开中转新页面，
# download 事件挂在新页面上，必须给足中转时间；等待用 Playwright 方法泵事件循环。
DOWNLOAD_WAIT_SECONDS = 60
DOWNLOAD_WAIT_TICKS   = DOWNLOAD_WAIT_SECONDS * 2  # 每 tick 500ms
# ─────────────────────────────────────────────────────────


def log(msg):
    """带时间戳的日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ═════════════════════════════════════════════════════════
#  进度管理
# ═════════════════════════════════════════════════════════

def load_progress() -> dict:
    """读取进度文件"""
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {}


def save_progress(data: dict):
    """保存进度文件"""
    PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ═════════════════════════════════════════════════════════
#  步骤1：抓取坚果云页面
# ═════════════════════════════════════════════════════════

def fetch_jianguoyun():
    """抓取坚果云分享页，保存HTML和截图。

    密码最多尝试 3 次（项目规则，避免触发坚果云封禁）。
    失败时直接抛出异常，停下来等用户确认新密码。
    """
    log("启动浏览器，访问坚果云...")

    MAX_PWD_ATTEMPTS = 3
    PASSWORD = "psw0528"

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=_headless)
        page = browser.new_page()
        page.goto("https://www.jianguoyun.com/p/DcEaxJgQ-P7XCRiJnL4FIAA", timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 填密码循环（最多 3 次）
        attempt = 0
        while True:
            pwd_input = page.query_selector('input#access-pwd')
            if not pwd_input:
                log("密码验证通过")
                break

            attempt += 1
            if attempt > MAX_PWD_ATTEMPTS:
                browser.close()
                raise RuntimeError(
                    f"坚果云密码已尝试 {MAX_PWD_ATTEMPTS} 次仍未通过，"
                    "按项目规则停下来问用户拿新密码。"
                )

            log(f"[密码 {attempt}/{MAX_PWD_ATTEMPTS}] 填入密码...")
            pwd_input.fill(PASSWORD)
            ok_btn = page.query_selector(".ok-button")
            if ok_btn:
                ok_btn.click()

            time.sleep(3)
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # 检查封禁提示
            err = page.query_selector('.error-msg')
            if err:
                err_text = err.inner_text()
                if "禁止访问" in err_text:
                    browser.close()
                    raise RuntimeError(
                        "坚果云封禁当前 IP（密码错误次数过多），"
                        "需要换 IP 或等待后再试。"
                    )
                elif "密码" in err_text and ("错误" in err_text or "失败" in err_text):
                    log(f"  [FAIL] 密码错误，还剩 {MAX_PWD_ATTEMPTS - attempt} 次机会")
                    continue

        # 保存截图和HTML
        (PROJECT_ROOT / "assets").mkdir(exist_ok=True)
        (PROJECT_ROOT / "data").mkdir(exist_ok=True)
        page.screenshot(path=str(PROJECT_ROOT / "assets" / "jianguoyun.png"), full_page=True)
        (PROJECT_ROOT / "data" / "jianguoyun_page.html").write_text(
            page.content(), encoding="utf-8"
        )

        browser.close()

    log("坚果云页面抓取完成")


# ═════════════════════════════════════════════════════════
#  步骤2：解析HTML提取条目
# ═════════════════════════════════════════════════════════

def parse_all_entries_from_html(html_path: Path) -> list[dict]:
    """从坚果云HTML中解析所有下载条目"""
    content = html_path.read_text(encoding="utf-8")

    # 去掉span标签干扰
    content = re.sub(r'<span class="hljs-selector-tag">', '', content)
    content = re.sub(r'<span class="hljs-selector-pseudo">', '', content)
    content = re.sub(r'<span class="hljs-section">', '', content)  # 2026-07-21 新增：覆盖大部分条目
    content = re.sub(r'</span>', '', content)

    # 格式: XXXX更新：名称：file_id  密码：pwd
    # 注：
    #   1. file_id 字符类允许 /，因为坚果云 HTML 偶发会在 file_id 前加脏字符 /（2026-06-09 修复，红线）
    #   2. 名称段用贪婪 .+，并强制 file_id 以 i 开头（lanzou 所有 ID 都是 i+字母数字）且总长 >= 10
    #      ——这让正则引擎在冒号面前能稳定停在「真正」的文件 ID 上。旧版 [^：:]+ 会被冒号截断，
    #      把 "JM:1074" 错配为 name="JM"、file_id="1074"（<6 字符虽被长度过滤掉但浪费了一次回溯）
    #   3. 分隔符与 file_id 之间允许 \s*，应对 "WP330:  iDDbw..." 这种双空格
    #   4. 行尾 $ 锚定 + MULTILINE，确保只匹配完整一行而非 HTML 标签内的片段
    pattern = r'^(\d{4}更新)[：:](.+)[：:]\s*(\/?i[a-zA-Z0-9/]{8,})(?:[：:\s]*密码[：:]([a-zA-Z0-9]+))?\s*$'

    entries = []
    for m in re.finditer(pattern, content, re.MULTILINE):
        date_str = m.group(1)
        name = m.group(2).strip()
        file_id = m.group(3).strip().lstrip('/')  # 容错：去掉坚果云脏字符 /
        password = m.group(4).strip() if m.group(4) else None

        if len(file_id) >= 6:
            entries.append({
                "index": date_str,
                "name": name,
                "file_id": file_id,
                "password": password,
                "line_no": len(entries) + 1,  # 简化的行号，用于排序
            })

    return entries


def parse_all_entries_from_txt(filepath: Path) -> list[dict]:
    """从本地txt文件中解析所有下载条目（与download.py一致）"""
    entries = []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, 1):
        line = line.strip()
        if not line or "：" not in line:
            continue
        normalized = line.replace("：", ":").replace("；", ";")
        m = re.match(r"^(\d{4}更新)\s*:\s*(.+?)\s*:\s*([A-Za-z0-9]+)", normalized)
        if not m:
            continue
        pwd_m = re.search(r"密码\s*:\s*([A-Za-z0-9]+)", normalized)
        entries.append({
            "index": m.group(1),
            "name": m.group(2).strip(),
            "file_id": m.group(3).strip(),
            "password": pwd_m.group(1).strip() if pwd_m else None,
            "line_no": line_no,
        })
    return entries


def find_last_date_line(entries: list[dict], date_str: str) -> int:
    """
    找到指定日期（如 "0331"）在所有条目中出现位置中行号最大的那个。
    这自然定位到最后一列（因为最后一列在文件中位置最靠后）。
    """
    matched = [e for e in entries if e["index"] == f"{date_str}更新"]
    if not matched:
        raise ValueError(f"未找到 {date_str}更新 对应的条目")
    return max(matched, key=lambda e: e["line_no"])["line_no"]


# ═════════════════════════════════════════════════════════
#  步骤3：下载新条目
# ═════════════════════════════════════════════════════════

def download_one(page, context, entry: dict, sink: dict) -> bool:
    """下载单个条目，返回是否成功。

    sink = {"items": [...]}：由 download_entries() 在 context 上一次性注册
    download 监听后传入。下载事件可能落在原页面，也可能落在点击后打开的
    中转新页面，所以只点击一次，再统一等事件，不按页面分别 expect_download。
    """
    url = LANZOU_BASE_URL + entry["file_id"]
    log(f"下载: {entry['name']} ({url})")

    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
    except Exception as e:
        log(f"  [FAIL] 页面加载失败: {e}")
        return False

    frame = page
    iframes = page.frames
    if len(iframes) > 1:
        for f in iframes[1:]:
            if f.url and "lanzoui" in f.url:
                frame = f
                break

    # 填密码
    if entry["password"]:
        try:
            pwd_box = frame.query_selector("input#pwd, input[name='pwd'], input[type='password']")
            if pwd_box:
                pwd_box.fill(entry["password"])
                submit = frame.query_selector("input#sub, button#sub, input[type='submit']")
                if submit:
                    submit.click()
                else:
                    pwd_box.press("Enter")
                frame.wait_for_load_state("networkidle")
                time.sleep(2)
        except Exception as e:
            log(f"  [WARN] 密码填写异常: {e}")

    # 找下载按钮
    download_btn = frame.query_selector(
        "a.btn, a.button, a[href*='down'], input.bott, "
        "a:has-text('下载'), a:has-text('普通下载'), button:has-text('下载')"
    )
    if not download_btn:
        log(f"  [FAIL] 未找到下载按钮")
        return False

    # 只点击一次 + 等 context 级 download 事件。
    # 旧实现先在原 page expect_download 空等 60s，再二次点击；对「打开中转
    # 新页面」的链接会必然失败（第二次点击时 context 已关闭）。
    # 注意：Playwright 同步 API 的事件循环只在调用其方法时泵，time.sleep
    # 不投递事件，必须用 wait_for_timeout 驱动，否则会出现「事件到达但
    # 文件没保存、还误判成功」的假阳性。
    sink["items"] = []
    try:
        download_btn.click()
    except Exception as e:
        log(f"  [FAIL] 下载按钮点击异常: {e}")
        return False

    for _ in range(DOWNLOAD_WAIT_TICKS):
        if sink["items"]:
            break
        try:
            page.wait_for_timeout(500)
        except Exception:
            try:
                context.pages[0].wait_for_timeout(500)
            except Exception:
                log("  [FAIL] 所有页面已关闭，无法继续等待下载")
                break

    if not sink["items"]:
        log(f"  [FAIL] 等待下载事件超时（{DOWNLOAD_WAIT_SECONDS}s）")
        return False

    download = sink["items"][0]
    try:
        save_name = download.suggested_filename or entry["name"]
        save_path = DOWNLOAD_DIR / save_name
        download.save_as(save_path)
        log(f"  [OK] 已保存: {save_name}")
        return True
    except Exception as e:
        log(f"  [FAIL] 保存下载文件异常: {e}")
        return False


def download_entries(entries: list[dict]) -> tuple[int, int]:
    """批量下载条目，返回 (成功数, 失败数)"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 边界日预检（2026-10-24）：起点过滤用 >= 语义，边界日首条必然在上次同步已
    # 下载过；无条件重试会重复点击下载按钮，早期实现会抛
    # "Target page ... has been closed"（JM1125/WP347 已复现 2 次）。
    # 产物已存在的条目直接跳过，匹配逻辑复用 verify_completeness
    # 的短 ID 前缀表（JM/WP/python 真实文件名与条目名不一致，见 §9 红线）。
    existing_stems = {f.name for f in DOWNLOAD_DIR.iterdir()}
    pending = []
    for entry in entries:
        name = entry["name"]
        hit = any(
            _file_matches_short_id(s[: -len(ext)], name)
            for s in existing_stems
            for ext in (".pdf", ".exe", ".zip")
            if s.endswith(ext)
        )
        if hit:
            log(f"[SKIP] 产物已存在，跳过下载: {entry['index']} {name}")
        else:
            pending.append(entry)

    if not pending:
        log("全部条目产物已存在，无需下载")
        return 0, 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=_headless,
            downloads_path=str(DOWNLOAD_DIR),
        )
        context = browser.new_context(accept_downloads=True)

        # context 级 download 监听：事件可能发生在原页面，也可能落在点击后
        # 打开的蓝奏云中转新页面。已有页面和未来新页面都挂上，避免按页面
        # 分别 expect_download 时漏掉新页面上的事件。
        sink = {"items": []}
        def _hook(pg):
            pg.on("download", lambda d: sink["items"].append(d))
        context.on("page", _hook)
        for pg in context.pages:
            _hook(pg)
        page = context.new_page()
        _hook(page)

        success = failed = 0
        for i, entry in enumerate(pending, 1):
            log(f"[{i}/{len(pending)}] {entry['index']} {entry['name']}")
            try:
                if download_one(page, context, entry, sink):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                log(f"  [FAIL] 处理异常: {e}")
                failed += 1
            time.sleep(1)

        browser.close()

    return success, failed


# ═════════════════════════════════════════════════════════
#  步骤4：解压
# ═════════════════════════════════════════════════════════

def extract_password(filename: str) -> str:
    """从文件名中提取数字作为密码"""
    numbers = re.findall(r"\d+", filename)
    return "".join(numbers)


def extract_with_7zip(archive: Path, password: str) -> bool:
    """用7-Zip解压"""
    cmd = [
        SEVENZIP, "x",
        str(archive),
        f"-p{password}",
        f"-o{archive.parent}",
        "-aoa", "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode in (0, 1)


def extract_with_zipfile(archive: Path, password: str) -> bool:
    """用内置zipfile解压"""
    import zipfile
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(path=archive.parent, pwd=password.encode())
        return True
    except Exception:
        return False


def extract_archives() -> tuple[int, int]:
    """解压所有压缩包，返回 (成功数, 失败数)"""
    archives = sorted(
        f for f in DOWNLOAD_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in ARCHIVE_SUFFIXES
    )

    if not archives:
        log("目录中没有压缩包需要解压")
        return 0, 0

    log(f"找到 {len(archives)} 个压缩包，开始解压...")
    success = failed = 0

    for archive in archives:
        password = extract_password(archive.stem)
        log(f"解压: {archive.name} (密码: {password})")

        if archive.suffix.lower() == ".zip":
            ok = extract_with_zipfile(archive, password)
            if not ok:
                ok = extract_with_7zip(archive, password)
        else:
            ok = extract_with_7zip(archive, password)

        if ok:
            log(f"  [OK] 解压成功")
            success += 1
        else:
            log(f"  [FAIL] 解压失败")
            failed += 1

    return success, failed


# ═════════════════════════════════════════════════════════
#  步骤5：处理 .exe 伪装PDF
# ═════════════════════════════════════════════════════════

def rename_exe_to_pdf() -> int:
    """
    检查下载目录中的 .exe 文件，如果文件头是 %PDF 则重命名为 .pdf。
    返回重命名的文件数量。
    """
    exe_files = sorted(DOWNLOAD_DIR.glob("*.exe"))
    if not exe_files:
        return 0

    renamed = 0
    for f in exe_files:
        with open(f, "rb") as fh:
            header = fh.read(5)
        if header == b"%PDF-":
            new_name = f.with_suffix(".pdf")
            if new_name.exists():
                log(f"跳过（已存在）: {f.name}")
                continue
            f.rename(new_name)
            log(f"重命名: {f.name} -> {new_name.name}")
            renamed += 1
        else:
            log(f"非PDF伪装，跳过: {f.name}")

    return renamed


# ═════════════════════════════════════════════════════════
#  步骤7（项目迭代）：完整性验证
# ═════════════════════════════════════════════════════════

# 命名约定映射：条目中叫 "WP330"，下载后实际文件叫 "外篇330.zip"
# ——这是源页面的命名 vs 蓝奏云原始上传名的差异。
WP_TO_WAIPIAN = re.compile(r"^WP(\d+)$")


def _candidate_filenames(name: str) -> list[str]:
    """根据条目名推导所有可能的下载文件名（去扩展名）"""
    candidates = [name]
    m = WP_TO_WAIPIAN.match(name)
    if m:
        candidates.append(f"外篇{m.group(1)}")
    return candidates


def _entry_short_id(entry_name: str) -> tuple[str, str]:
    """
    把 entry_name 解析为 (前缀, 数字串)，用于模糊匹配下载/产物文件名。
    例: 'JM1066' -> ('JM', '1066')
        'JM:1074' -> ('JM', '1074')   —— 冒号归一为 JM
        'WP330' -> ('WP', '330')  —— 实际文件名前缀为 外篇330
        'python873' -> ('python', '873')  —— 实际为 python学习材料873
    """
    m = re.match(r"^(JM:?|WP|python)(\d+)$", entry_name)
    if not m:
        return (entry_name, "")
    prefix = m.group(1).rstrip(":")  # 'JM:' -> 'JM'
    return (prefix, m.group(2))


_ENTRY_DATE_RE = re.compile(r"^(\d{2})(\d{2})更新$")


def build_entry_dates(entries: list[dict], latest_year: int = None) -> dict[int, tuple]:
    """按页面顺序重建每个条目的发布日期，返回 {entries 下标: (year, month, day)}。

    坚果云页面是「旧 -> 新」的累计清单（一份页面跨 5 年），跨年处 MMDD 回绕；
    以**末条（最新）**所在年份为锚，逐条倒推。绝对不能按「当前年 + 条目月份」
    直接推，否则历史条目会被推到错误的年份（2026-11 曾因此把 JM1 标成 2021-01）。

    非法日期（如页面上的 ``0145更新``）返回 None，由调用方跳过。
    """
    parsed = []
    for e in entries:
        m = _ENTRY_DATE_RE.match((e.get("index") or "").strip())
        mm, dd = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        parsed.append((mm, dd) if 1 <= mm <= 12 and 1 <= dd <= 31 else None)

    valid = [p for p in parsed if p]
    if not valid:
        return {}
    # 方向判断：正向回绕次数 ≈ 跨年数；若过多说明页面是「新 -> 旧」
    wraps = sum(1 for i in range(1, len(parsed))
                if parsed[i] and parsed[i - 1] and parsed[i] < parsed[i - 1])
    order = list(range(len(parsed)))
    if wraps > len(valid) / 4:
        order.reverse()

    base_year = latest_year or datetime.now().year
    last = parsed[order[-1]]
    if last and last[0] > datetime.now().month + 1:
        base_year -= 1          # 末条是 12 月而当前是 1 月

    out = {}
    year, prev = base_year, None
    for i in reversed(order):   # 新 -> 旧
        d = parsed[i]
        if d is None:
            out[i] = None
            continue
        if prev is not None and d[0] > prev[0]:
            year -= 1           # 往回走月份变大 => 跨到上一年
        prev = d
        out[i] = (year, d[0], d[1])
    return out


def _make_jm_namer(entries: list[dict]):
    """构造 JM 命名器：pdf_stem -> ``YY.MM月-JMxxx-标题``。

    日期取坚果云条目日期（见 build_entry_dates），并以 **JM 编号顺序为第一优先级**
    做单调约束：编号递增时年月不得倒退（编号才是发布顺序的事实源）。
    非 JM 或编号不在本批条目内时返回 None，调用方沿用原名。
    """
    dates = build_entry_dates(entries)
    by_num = {}
    for i, e in enumerate(entries):
        num = extract_jm_num(e["name"])
        d = dates.get(i)
        if num is not None and d and num not in by_num:
            by_num[num] = d[:2]        # 同编号取最早出现

    # 单调化：编号递增 => 年月不减
    last = None
    for num in sorted(by_num):
        y, m = by_num[num]
        if last is not None and (y, m) < last:
            log(f"[WARN] JM{num} 条目日期 {y}-{m:02d} 早于前一号 {last[0]}-{last[1]:02d}，按编号顺序修正")
            by_num[num] = last
        last = by_num[num]

    def namer(pdf_stem: str):
        num = extract_jm_num(pdf_stem)
        if num is None or num not in by_num:
            return None
        parsed = parse_legacy(pdf_stem)
        title = (parsed["title"] if parsed else "") or ""
        y, m = by_num[num]
        try:
            return build_stem(y, m, num, title)
        except Exception:
            return None

    return namer


def _file_matches_short_id(file_stem: str, entry_name: str) -> bool:
    """判断 file_stem（无扩展名的文件名）是否属于 entry_name 对应的下载产物。

    兼容两套 JM 命名：
      - 下载目录原名 ``JM1140 小弟与帮派``
      - 知识库新名 ``26.10月-JM1140-小弟与帮派``（2026-11-12 起）
    """
    prefix, num = _entry_short_id(entry_name)
    if not num:
        return file_stem.startswith(entry_name)
    if prefix == "JM" and re.search(rf"-JM{num}-", file_stem):
        return True
    # 不同系列对应的实际文件名前缀
    real_prefixes = {
        "JM": ["JM"],
        "WP": ["外篇", "WP"],
        # python 系列：标准是 "python学习材料"；蓝奏云偶发返回误拼 "ptyhon学习材料"（如 python904）
        "python": ["python学习材料", "ptyhon学习材料"],
    }.get(prefix, [prefix])
    for rp in real_prefixes:
        candidate = f"{rp}{num}"
        if file_stem == candidate:
            return True
        if file_stem.startswith(candidate + " "):
            return True
    return False


def _check_entry_status(entry: dict, download_stems: set, md_stems: set) -> dict:
    """
    检查单个条目在 download/markdown 两侧的存在状态。

    关键差异：解析器拿到的 name 是短 ID（"JM1066"、"WP330"、"python873"），
    但下载后的实际文件名是 lanzou 返回的全标题（"JM1066 从冻省展开（2）.pdf"、
    "外篇330.zip"），所以按 _file_matches_short_id 做基于短 ID 的模糊匹配。
    """
    name = entry["name"]

    def find_match(stems: set, ext: str):
        for s in stems:
            if not s.endswith(ext):
                continue
            file_stem = s[: -len(ext)]
            if _file_matches_short_id(file_stem, name):
                return s
        return None

    pdf_hit = find_match(download_stems, ".pdf")
    exe_hit = find_match(download_stems, ".exe")
    zip_hit = find_match(download_stems, ".zip")
    md_hit = find_match(md_stems, ".md")

    # 只有 JM 系列要求生成 Markdown；python/外篇/WP 只下载+归档，
    # 这些条目即便没有 .md 也不算 needs_convert（否则验证长期假阳性）。
    if not is_jm_series(name):
        if pdf_hit:
            status = "ok"
        elif exe_hit:
            status = "needs_rename"
        elif zip_hit:
            status = "needs_unzip"
        else:
            status = "missing"
    elif pdf_hit and md_hit:
        status = "ok"
    elif pdf_hit and not md_hit:
        status = "needs_convert"
    elif exe_hit and not pdf_hit:
        status = "needs_rename"  # .exe 还没重命名/解压
    elif zip_hit and not md_hit:
        status = "needs_unzip"
    elif not (pdf_hit or exe_hit or zip_hit):
        status = "missing"
    else:
        status = "ok"

    return {
        "index": entry["index"],
        "name": name,
        "file_id": entry["file_id"],
        "download": pdf_hit or exe_hit or zip_hit,
        "markdown": md_hit,
        "status": status,
    }


def _detect_sequence_gaps(entries: list[dict], prefix: str) -> list[int]:
    """
    在形如 "JM1066"、"WP330"、"python学习材料873" 的命名中检测断号。
    prefix 是正则字面量前缀，例如 'JM'、'WP'、'python学习材料'。
    返回该系列缺失的编号列表（按升序）。允许名称中含冒号（'JM:1074'）。
    """
    num_pat = re.compile(rf"^{re.escape(prefix)}:?(\d+)$")
    nums = []
    for e in entries:
        m = num_pat.match(e["name"])
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return []
    full = set(range(min(nums), max(nums) + 1))
    return sorted(full - set(nums))


def verify_completeness(
    entries: list[dict],
    last_date: str,
    latest_date: str,
    download_dir: Path = DOWNLOAD_DIR,
    markdown_dir: Path = MARKDOWN_DIR,
    output_path: Path = None,
) -> dict:
    """
    对 last_date ~ latest_date 范围内的所有条目做完整性检查：
    1) 每个条目 4 个状态：download / markdown / 是否解压 / 是否完成
    2) 命名序列断号：JM / python学习材料 / WP 三个系列是否缺号
    返回 dict，同时落盘到 data/completeness_report.json
    """
    start_line = find_last_date_line(entries, last_date)
    target = [e for e in entries if e["line_no"] >= start_line]

    download_stems = set()
    if download_dir.exists():
        for p in download_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".pdf", ".exe", ".zip"):
                download_stems.add(p.name)

    md_stems = set()
    if markdown_dir.exists():
        for p in markdown_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".md":
                md_stems.add(p.name)

    per_entry = [_check_entry_status(e, download_stems, md_stems) for e in target]

    by_status = {"ok": 0, "needs_convert": 0, "needs_unzip": 0, "missing": 0}
    for r in per_entry:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    missing_rows = [r for r in per_entry if r["status"] == "missing"]
    needs_convert_rows = [r for r in per_entry if r["status"] == "needs_convert"]
    needs_unzip_rows = [r for r in per_entry if r["status"] == "needs_unzip"]

    gaps = {
        "JM": _detect_sequence_gaps(target, "JM"),
        "WP": _detect_sequence_gaps(target, "WP"),
        "python学习材料": _detect_sequence_gaps(target, "python学习材料"),
    }

    report = {
        "anchor_date": last_date,
        "latest_date": latest_date,
        "checked_count": len(target),
        "by_status": by_status,
        "missing": missing_rows,
        "needs_convert": needs_convert_rows,
        "needs_unzip": needs_unzip_rows,
        "sequence_gaps": gaps,
    }

    log("\n" + "=" * 50)
    log("步骤9/9：完整性验证")
    log("=" * 50)
    log(f"检查范围: {last_date} ~ {latest_date}，共 {len(target)} 条")
    log(f"完整    : {by_status['ok']}")
    log(f"待转换  : {by_status['needs_convert']}")
    log(f"待解压  : {by_status['needs_unzip']}")
    log(f"缺失    : {by_status['missing']}")
    if any(gaps.values()):
        log("序列断号:")
        for series, missing in gaps.items():
            if missing:
                log(f"  {series}: 缺 {len(missing)} 个 -> {missing[:20]}{'...' if len(missing)>20 else ''}")
    if missing_rows:
        log("缺失明细 (前 20):")
        for r in missing_rows[:20]:
            log(f"  {r['index']} {r['name']} -> {r['file_id']}")
    if needs_convert_rows:
        log("已下载但未转 Markdown (前 10):")
        for r in needs_convert_rows[:10]:
            log(f"  {r['index']} {r['name']}")
    if needs_unzip_rows:
        log("ZIP 还在未解压 (前 10):")
        for r in needs_unzip_rows[:10]:
            log(f"  {r['index']} {r['name']}")

    if output_path is None:
        output_path = PROJECT_ROOT / "data" / "completeness_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"报告写入: {output_path}")

    return report


# ═════════════════════════════════════════════════════════
#  主控流程
# ═════════════════════════════════════════════════════════

_headless = False


def main():
    global _headless

    # 解析命令行参数
    last_date = None
    for arg in sys.argv[1:]:
        if arg == "--headless":
            _headless = True
        elif arg.startswith("-"):
            log(f"未知参数: {arg}")
        else:
            last_date = arg.strip()

    # 读取进度
    progress = load_progress()

    if last_date is None:
        last_date = progress.get("last_sync_date")

    if not last_date:
        print("=" * 50)
        print("首次运行，请输入上次同步日期（如 0331）：")
        last_date = input("> ").strip()
        print("=" * 50)

    today = datetime.now().strftime("%Y-%m-%d")
    log(f"上次同步日期: {last_date}")
    log(f"今天: {today}")

    # ── 步骤1：抓取坚果云 ──
    log("\n" + "=" * 50)
    log("步骤1/9：抓取坚果云页面")
    log("=" * 50)
    try:
        fetch_jianguoyun()
    except Exception as e:
        log(f"[FAIL] 抓取失败: {e}")
        return

    # ── 步骤2：解析条目 ──
    log("\n" + "=" * 50)
    log("步骤2/9：解析页面提取条目")
    log("=" * 50)

    # 优先使用本地txt文件（如果存在），否则从HTML解析
    if SOURCE_FILE.exists():
        all_entries = parse_all_entries_from_txt(SOURCE_FILE)
        log(f"从本地文件解析到 {len(all_entries)} 个条目")
    else:
        html_path = PROJECT_ROOT / "data" / "jianguoyun_page.html"
        all_entries = parse_all_entries_from_html(html_path)
        log(f"从HTML解析到 {len(all_entries)} 个条目")

    if not all_entries:
        log("[FAIL] 未解析到任何条目")
        return

    # 找到上次日期之后的条目（多个相同日期选行号最大的）
    try:
        start_line = find_last_date_line(all_entries, last_date)
    except ValueError as e:
        log(f"[FAIL] {e}")
        return

    new_entries = [e for e in all_entries if e["line_no"] >= start_line]

    if not new_entries:
        log(f"\n没有新条目需要下载（上次已同步到最新）")
        log(f"同步结束")
        return

    latest_date = new_entries[-1]["index"].replace("更新", "")
    log(f"发现 {len(new_entries)} 个新条目 ({last_date} ~ {latest_date})")
    for e in new_entries[:5]:
        pwd = f" 密码:{e['password']}" if e["password"] else ""
        log(f"  [{e['index']}] {e['name']} -> {e['file_id']}{pwd}")
    if len(new_entries) > 5:
        log(f"  ... 还有 {len(new_entries) - 5} 条")

    # ── 步骤3：下载 ──
    log("\n" + "=" * 50)
    log(f"步骤3/9：下载新条目 ({last_date} ~ {latest_date})")
    log("=" * 50)
    dl_success, dl_failed = download_entries(new_entries)
    log(f"下载完成: 成功 {dl_success} 个, 失败 {dl_failed} 个")

    # ── 步骤4：解压 ──
    log("\n" + "=" * 50)
    log("步骤4/9：解压压缩包")
    log("=" * 50)
    ex_success, ex_failed = extract_archives()
    log(f"解压完成: 成功 {ex_success} 个, 失败 {ex_failed} 个")

    # ── 步骤5：处理 .exe 伪装 ──
    log("\n" + "=" * 50)
    log("步骤5/9：处理 .exe 伪装文件")
    log("=" * 50)
    renamed = rename_exe_to_pdf()
    log(f"重命名完成: {renamed} 个 .exe -> .pdf")

    # ── 步骤6：PDF → Markdown 转换 ──
    log("\n" + "=" * 50)
    log("步骤6/9：PDF 转 Markdown")
    log("=" * 50)

    # 自动检测目录内容并推荐模式
    md_mode = auto_detect_mode(DOWNLOAD_DIR)
    log(f"转换模式: {md_mode}")

    jm_namer = _make_jm_namer(new_entries)
    md_converter = PdfConverter(mode=md_mode)
    md_summary = md_converter.convert_batch(DOWNLOAD_DIR, MARKDOWN_DIR, namer=jm_namer)
    md_stats = md_summary.get("stats", {})
    log(f"转换完成: 成功 {md_stats.get('passed', 0)} 个, 警告 {md_stats.get('warn', 0)} 个, 失败 {md_stats.get('failed', 0)} 个")
    if md_stats.get("skipped_non_jm"):
        log(f"跳过    : {md_stats['skipped_non_jm']} 个非 JM 系列（只下载+归档，不转 MD）")
    if md_stats.get("skipped"):
        log(f"跳过    : {md_stats['skipped']} 个 (模式过重，light已足够)")
    # 转换即排版（pdf_to_md.py 内建门禁，见 AGENTS.md §4.5）。
    # failed 里可能含排版校验失败而拒绝落盘的文件，故单独打印通过数便于核对。
    log(f"排版门禁: {md_stats.get('layout_ok', 0)} 个通过（校验失败不落盘）")

    # ── 步骤7：归档 PDF（只进项目资料库；知识库只放 MD） ──
    # archive_pdfs 返回的 (copied, skipped)：拷贝数 / 已存在跳过数。
    log("\n" + "=" * 50)
    log("步骤7/9：归档 PDF 到项目资料库（知识库只放 MD）")
    log("=" * 50)
    archived, archive_skipped = archive_pdfs(namer=jm_namer)
    log(f"归档完成(所有目的地合计): 拷贝 {archived} 个, 跳过 {archive_skipped} 个已存在")

    # ── 更新进度 ──
    log("\n" + "=" * 50)
    log("步骤8/9：更新同步进度")
    log("=" * 50)

    # 进度锚点只在本次全部下载成功时推进。有失败条目时保持原锚点，
    # 下次运行的 [SKIP] 预检会跳过已落地产物，只重试失败条目；
    # 若仍推进到 latest_date，失败条目将被永久跳过（只能靠步骤9兜底）。
    # 注意：history entry 字段固定，失败信息只能写进既有的 note 字段（§9 红线）。
    anchor_date = latest_date if dl_failed == 0 else progress.get("last_sync_date", last_date)
    if dl_failed == 0:
        progress["last_sync_date"] = latest_date
        progress["last_sync_full_date"] = today
        progress["last_sync_range"] = f"{last_date}~{latest_date}"
        progress["last_sync_count"] = len(new_entries)
    progress["total_downloaded"] = progress.get("total_downloaded", 0) + dl_success
    record = {
        "date": today,
        "range": f"{last_date}~{latest_date}",
        "count": len(new_entries),
        "downloaded": dl_success,
        "extracted": ex_success,
        "renamed": renamed,
        "converted": md_stats.get("passed", 0),
    }
    if dl_failed:
        record["note"] = (
            f"下载失败 {dl_failed} 个，进度锚点保持 {anchor_date}；"
            "下次同步由 [SKIP] 预检只重试失败条目"
        )
    progress["history"] = progress.get("history", []) + [record]
    save_progress(progress)

    # ── 完成报告 ──
    log("\n" + "=" * 50)
    log("同步完成！")
    log("=" * 50)
    log(f"本次同步: {len(new_entries)} 个文件 ({last_date} ~ {latest_date})")
    log(f"下载成功: {dl_success} 个")
    log(f"解压成功: {ex_success} 个")
    log(f"重命名  : {renamed} 个 (exe->pdf)")
    log(f"Markdown: {md_stats.get('passed', 0)} 个 (模式: {md_mode})")
    log(f"最新时点: {latest_date}")
    if dl_failed:
        log(f"[WARN] 本次有 {dl_failed} 个条目下载失败，进度锚点未推进（仍为 {anchor_date}）")
    log(f"下次运行将自动从 {anchor_date} 继续")
    log("=" * 50)

    # ── 步骤8：完整性验证 ──
    verify_completeness(all_entries, last_date, latest_date)


if __name__ == "__main__":
    main()
