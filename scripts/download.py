"""
从本地文件读取下载条目，执行批量下载

逻辑：
  1. 每次下载前，用户输入"上次执行日期"（如 0331）
  2. 脚本找到该日期在文件中所有出现位置，取行号最大的那条之后的所有条目
  3. 这就自然定位到最后一列（因为最后一列在文件中位置最靠后）
  4. 文件名强制使用条目名称（避免蓝奏云返回的 UUID 乱码）

用法：python download.py 0506
"""

import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── 配置 ──────────────────────────────────────────────────
SOURCE_FILE    = Path(r"C:\Users\Administrator\Downloads\特殊秘籍20240405.txt")
LANZOU_BASE_URL = "https://lanzoui.com/"
DOWNLOAD_DIR    = Path(r"C:\Users\allenwywang\allenwywang的同步盘\Allen documents\新建文件夹")
# ─────────────────────────────────────────────────────────


def parse_all_entries(filepath: Path) -> list[dict]:
    """解析文件中所有下载条目，返回 [{index, name, file_id, password, line_no}]"""
    entries = []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, 1):
        line = line.strip()
        if not line or "：" not in line:
            continue
        normalized = line.replace("：", ":").replace("；", ";").replace("：", ":")
        m = re.match(r"^(\d{4}更新)\s*:\s*(.+?)\s*:\s*([A-Za-z0-9]+)", normalized)
        if not m:
            continue
        index   = m.group(1)
        name    = m.group(2).strip()
        file_id = m.group(3).strip()
        if len(file_id) < 6:
            continue
        pwd_m = re.search(r"密码\s*:\s*([A-Za-z0-9]+)", normalized)
        password = pwd_m.group(1).strip() if pwd_m else None
        entries.append({
            "index":    index,
            "name":     name,
            "file_id":  file_id,
            "password": password,
            "line_no":  line_no,
        })
    return entries


def find_last_date_line(entries: list[dict], date_str: str) -> int:
    """
    找到指定日期（如 "0331"）在所有条目中出现位置中行号最大的那个
    返回该条目的 line_no
    """
    matched = [e for e in entries if e["index"] == f"{date_str}更新"]
    if not matched:
        raise ValueError(f"未找到 {date_str}更新 对应的条目")
    # 取行号最大的那个（最后一列）
    return max(matched, key=lambda e: e["line_no"])["line_no"]


def download_one(page, context, entry: dict, download_dir: Path):
    """打开蓝奏云页面，填密码，点击下载，强制用条目名称保存文件"""
    url = LANZOU_BASE_URL + entry["file_id"]
    print(f"\n[下载] {entry['name']}  ({url})")

    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    frame = page
    iframes = page.frames
    if len(iframes) > 1:
        for f in iframes[1:]:
            if f.url and "lanzoui" in f.url:
                frame = f
                break

    if entry["password"]:
        pwd_box = frame.query_selector("input#pwd, input[name='pwd'], input[type='password']")
        if pwd_box:
            print(f"      填写密码: {entry['password']}")
            pwd_box.fill(entry["password"])
            submit_btn = frame.query_selector("input#sub, button#sub, input[type='submit']")
            if submit_btn:
                submit_btn.click()
            else:
                pwd_box.press("Enter")
            frame.wait_for_load_state("networkidle")
            time.sleep(2)

    download_btn = frame.query_selector(
        "a.btn, a.button, a[href*='down'], input.bott, "
        "a:has-text('下载'), a:has-text('普通下载'), button:has-text('下载')"
    )
    if not download_btn:
        print(f"      [WARN] 未找到下载按钮，跳过 {entry['name']}")
        return

    print(f"      点击下载按钮，等待文件保存…")

    try:
        with page.expect_download(timeout=60000) as dl_info:
            download_btn.click()
        download = dl_info.value
        suggested = download.suggested_filename
        save_name = suggested if suggested else entry["name"]
        save_path = download_dir / save_name
        download.save_as(save_path)
        print(f"      [OK] 已保存: {save_path}  ({suggested})")
        return
    except PWTimeout:
        pass
    except Exception:
        pass

    try:
        with context.expect_page(timeout=10000) as new_page_info:
            download_btn.click()
        new_page = new_page_info.value
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
            suggested = download.suggested_filename
            save_name = suggested if suggested else entry["name"]
            save_path = download_dir / save_name
            download.save_as(save_path)
            print(f"      [OK] 已保存: {save_path}  ({suggested})")
        else:
            print(f"      [FAIL] 新页面中也未找到下载按钮")
        new_page.close()
    except Exception as e:
        print(f"      [FAIL] 下载失败: {e}")


def main():
    print(f"读取本地文件: {SOURCE_FILE}\n")

    all_entries = parse_all_entries(SOURCE_FILE)
    print(f"共解析到 {len(all_entries)} 个条目\n")

    # 获取上次执行日期（支持命令行参数或交互输入）
    if len(sys.argv) > 1:
        last_date = sys.argv[1].strip()
        print(f"命令行传入日期: {last_date}")
    else:
        last_date = input("请输入上次执行日期（如 0331，上次执行到哪一天就填哪一天）: ").strip()

    # 找到该日期在最后一列的位置（行号最大的那个）
    start_line = find_last_date_line(all_entries, last_date)

    # 筛选从 start_line 之后的所有条目
    entries = [e for e in all_entries if e["line_no"] > start_line]

    if not entries:
        print(f"\n⚠ 从 {last_date}更新 之后没有找到任何条目")
        return

    print(f"\n从 {last_date}更新（行{start_line}）之后筛选到 {len(entries)} 条：\n")
    for e in entries[:10]:
        pwd = f"  密码:{e['password']}" if e["password"] else ""
        print(f"  [{e['index']}] {e['name']} → {e['file_id']}{pwd}")
    if len(entries) > 10:
        print(f"  ... 还有 {len(entries) - 10} 条")
    print()

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            downloads_path=str(DOWNLOAD_DIR),
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        total = len(entries)
        for i, entry in enumerate(entries, 1):
            print(f"\n── 第 {i}/{total} 个 ──")
            print(f"      [{entry['index']}] {entry['name']} → {entry['file_id']}"
                  + (f"  密码:{entry['password']}" if entry["password"] else ""))
            try:
                download_one(page, context, entry, DOWNLOAD_DIR)
            except Exception as e:
                print(f"      [FAIL] 处理 [{entry['index']}] 时出错: {e}")
            time.sleep(1)

        print(f"\n全部完成！共下载 {total} 个文件，保存在: {DOWNLOAD_DIR}")
        browser.close()


if __name__ == "__main__":
    main()