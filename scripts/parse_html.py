"""
解析坚果云分享页html，提取0506更新之后的所有条目
"""
import re
from pathlib import Path

HTML_FILE = Path("../data/jianguoyun_page.html")

def parse_entries(html_path: Path) -> list[dict]:
    """从html中解析下载条目"""
    content = html_path.read_text(encoding="utf-8")

    # 先去掉span标签的干扰
    content = re.sub(r'<span class="hljs-selector-tag">', '', content)
    content = re.sub(r'<span class="hljs-selector-pseudo">', '', content)
    content = re.sub(r'</span>', '', content)

    # 格式: XXXX更新：名称：file_id  密码：pwd
    pattern = r'(\d{4}更新)[：:]([^：:]+)[：:]([a-zA-Z0-9]+)(?:\s+密码[：:]([a-zA-Z0-9]+))?'

    entries = []
    for m in re.finditer(pattern, content):
        date_str = m.group(1)  # 如 "0506更新"
        name = m.group(2).strip()
        file_id = m.group(3).strip()
        password = m.group(4).strip() if m.group(4) else None

        if len(file_id) >= 6:
            entries.append({
                "date": date_str,
                "name": name,
                "file_id": file_id,
                "password": password,
            })

    return entries

def main():
    entries = parse_entries(HTML_FILE)
    print(f"共解析到 {len(entries)} 个条目\n")

    # 找到最后一个0506更新的位置
    start_idx = None
    for i, e in enumerate(entries):
        if e["date"] == "0506更新":
            start_idx = i

    if start_idx is None:
        print("未找到0506更新")
        return

    print(f"最后一个0506更新位于索引 {start_idx}，之后有 {len(entries) - start_idx - 1} 条\n")

    # 筛选0506更新之后的所有条目
    new_entries = entries[start_idx + 1:]

    print(f"从0506更新之后筛选到 {len(new_entries)} 条：\n")
    for e in new_entries:
        pwd = f"  密码:{e['password']}" if e["password"] else ""
        print(f"  [{e['date']}] {e['name']} → {e['file_id']}{pwd}")

    print(f"\n共 {len(new_entries)} 条待下载")

    # 保存到文件供下载脚本使用 - 格式与download_from_local.py兼容
    output = []
    for e in new_entries:
        pwd_str = f"  密码:{e['password']}" if e["password"] else ""
        output.append(f"{e['date']}：{e['name']}：{e['file_id']}{pwd_str}")

    Path("../data/new_entries.txt").write_text("\n".join(output), encoding="utf-8")
    print(f"\n已保存到 new_entries.txt")


if __name__ == "__main__":
    main()