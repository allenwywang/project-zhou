"""
茶馆系列文件同步 - 一键同步主控脚本

用法：
    cd scripts
    python sync.py              # 默认从上次同步时点继续
    python sync.py 0331         # 手动指定上次同步日期（首次运行）
    python sync.py --headless   # 后台运行（不显示浏览器窗口）

流程：
    1. 读取 progress.json 获取上次同步日期
    2. 抓取坚果云页面
    3. 解析 HTML 提取所有条目
    4. 从上次同步日期（最后一列最新位置）开始下载
    5. 解压压缩包
    6. 处理 .exe 伪装 PDF 文件
    7. PDF → Markdown 转换（含图片检测和双引擎质检）
    8. 更新 progress.json
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# 导入 PDF 转换器
sys.path.insert(0, str(Path(__file__).parent))
from pdf_to_md import PdfConverter, auto_detect_mode

# ── 配置 ──────────────────────────────────────────────────
PROJECT_ROOT    = Path(__file__).parent.parent
PROGRESS_FILE   = PROJECT_ROOT / "progress.json"
SOURCE_FILE     = Path(r"C:\Users\Administrator\Downloads\特殊秘籍20240405.txt")
DOWNLOAD_DIR    = Path(r"C:\Users\allenwywang\allenwywang的同步盘\Allen documents\新建文件夹")
LANZOU_BASE_URL = "https://lanzoui.com/"
SEVENZIP        = r"C:\Program Files\7-Zip\7z.exe"
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
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
    """抓取坚果云分享页，保存HTML和截图"""
    log("启动浏览器，访问坚果云...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=_headless)
        page = browser.new_page()
        page.goto("https://www.jianguoyun.com/p/DcEaxJgQ-P7XCRiJnL4FIAA", timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 填密码
        pwd_input = page.query_selector('input#access-pwd')
        if pwd_input:
            log("填入访问密码...")
            pwd_input.fill("0403")
            ok_btn = page.query_selector(".ok-button")
            if ok_btn:
                ok_btn.click()
                time.sleep(3)

        page.wait_for_load_state("networkidle")
        time.sleep(5)

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
    content = re.sub(r'</span>', '', content)

    # 格式: XXXX更新：名称：file_id  密码：pwd
    pattern = r'(\d{4}更新)[：:]([^：:]+)[：:]([a-zA-Z0-9]+)(?:\s+密码[：:]([a-zA-Z0-9]+))?'

    entries = []
    for m in re.finditer(pattern, content):
        date_str = m.group(1)
        name = m.group(2).strip()
        file_id = m.group(3).strip()
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

def download_one(page, context, entry: dict) -> bool:
    """下载单个条目，返回是否成功"""
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

    # 尝试直接下载
    try:
        with page.expect_download(timeout=60000) as dl_info:
            download_btn.click()
        download = dl_info.value
        save_name = download.suggested_filename or entry["name"]
        save_path = DOWNLOAD_DIR / save_name
        download.save_as(save_path)
        log(f"  [OK] 已保存: {save_name}")
        return True
    except (PWTimeout, Exception):
        pass

    # 尝试新页面下载
    try:
        with context.expect_page(timeout=10000) as new_info:
            download_btn.click()
        new_page = new_info.value
        new_page.wait_for_load_state("networkidle")
        time.sleep(3)
        real_btn = new_page.query_selector(
            "a.btn, a.button, input.bott, "
            "a:has-text('下载'), a:has-text('普通下载'), button:has-text('下载')"
        )
        if real_btn:
            with new_page.expect_download(timeout=60000) as dl_info:
                real_btn.click()
            download = dl_info.value
            save_name = download.suggested_filename or entry["name"]
            save_path = DOWNLOAD_DIR / save_name
            download.save_as(save_path)
            log(f"  [OK] 已保存: {save_name}")
            new_page.close()
            return True
        else:
            log(f"  [FAIL] 新页面中未找到下载按钮")
            new_page.close()
            return False
    except Exception as e:
        log(f"  [FAIL] 下载异常: {e}")
        return False


def download_entries(entries: list[dict]) -> tuple[int, int]:
    """批量下载条目，返回 (成功数, 失败数)"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=_headless,
            downloads_path=str(DOWNLOAD_DIR),
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        success = failed = 0
        for i, entry in enumerate(entries, 1):
            log(f"[{i}/{len(entries)}] {entry['index']} {entry['name']}")
            try:
                if download_one(page, context, entry):
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
    log("步骤1/5：抓取坚果云页面")
    log("=" * 50)
    try:
        fetch_jianguoyun()
    except Exception as e:
        log(f"[FAIL] 抓取失败: {e}")
        return

    # ── 步骤2：解析条目 ──
    log("\n" + "=" * 50)
    log("步骤2/5：解析页面提取条目")
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

    new_entries = [e for e in all_entries if e["line_no"] > start_line]

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
    log(f"步骤3/5：下载新条目 ({last_date} ~ {latest_date})")
    log("=" * 50)
    dl_success, dl_failed = download_entries(new_entries)
    log(f"下载完成: 成功 {dl_success} 个, 失败 {dl_failed} 个")

    # ── 步骤4：解压 ──
    log("\n" + "=" * 50)
    log("步骤4/5：解压压缩包")
    log("=" * 50)
    ex_success, ex_failed = extract_archives()
    log(f"解压完成: 成功 {ex_success} 个, 失败 {ex_failed} 个")

    # ── 步骤5：处理 .exe 伪装 ──
    log("\n" + "=" * 50)
    log("步骤5/7：处理 .exe 伪装文件")
    log("=" * 50)
    renamed = rename_exe_to_pdf()
    log(f"重命名完成: {renamed} 个 .exe -> .pdf")

    # ── 步骤6：PDF → Markdown 转换 ──
    log("\n" + "=" * 50)
    log("步骤6/7：PDF 转 Markdown")
    log("=" * 50)

    # 自动检测目录内容并推荐模式
    md_mode = auto_detect_mode(DOWNLOAD_DIR)
    log(f"转换模式: {md_mode}")

    md_converter = PdfConverter(mode=md_mode)
    md_summary = md_converter.convert_batch(DOWNLOAD_DIR, DOWNLOAD_DIR.parent / "markdown")
    md_stats = md_summary.get("stats", {})
    log(f"转换完成: 成功 {md_stats.get('passed', 0)} 个, 警告 {md_stats.get('warn', 0)} 个, 失败 {md_stats.get('failed', 0)} 个")
    if md_stats.get("skipped"):
        log(f"跳过    : {md_stats['skipped']} 个 (模式过重，light已足够)")

    # ── 更新进度 ──
    log("\n" + "=" * 50)
    log("步骤7/7：更新同步进度")
    log("=" * 50)

    progress["last_sync_date"] = latest_date
    progress["last_sync_full_date"] = today
    progress["last_sync_range"] = f"{last_date}~{latest_date}"
    progress["last_sync_count"] = len(new_entries)
    progress["total_downloaded"] = progress.get("total_downloaded", 0) + dl_success
    progress["history"] = progress.get("history", []) + [{
        "date": today,
        "range": f"{last_date}~{latest_date}",
        "count": len(new_entries),
        "downloaded": dl_success,
        "extracted": ex_success,
        "renamed": renamed,
        "converted": md_stats.get("passed", 0),
    }]
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
    log(f"下次运行将自动从 {latest_date} 继续")
    log("=" * 50)


if __name__ == "__main__":
    main()
