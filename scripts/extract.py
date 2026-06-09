"""
批量解压脚本
- 扫描指定目录下所有压缩包（zip / rar / 7z）
- 解压密码 = 文件名中提取的数字
- 解压到压缩包所在文件夹
"""

import re
import subprocess
import zipfile
from pathlib import Path

# 支持的压缩文件扩展名
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}

# ── 配置 ──────────────────────────────────────────────────
DOWNLOAD_DIR = Path(r"C:\Users\allenwywang\allenwywang的同步盘\Allen documents\新建文件夹")
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
# ─────────────────────────────────────────────────────────


def extract_password(filename: str) -> str:
    """从文件名中提取所有数字作为密码，例如 JM1014.zip → '1014'"""
    numbers = re.findall(r"\d+", filename)
    return "".join(numbers)


def extract_with_zipfile(archive: Path, password: str) -> bool:
    """用内置 zipfile 解压 .zip 文件，返回是否成功"""
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(path=archive.parent, pwd=password.encode())
        return True
    except RuntimeError as e:
        if "Bad password" in str(e) or "password required" in str(e).lower():
            return False
        raise
    except Exception:
        return False


def extract_with_7zip(archive: Path, password: str) -> bool:
    """用 7-Zip 解压任意格式压缩包，返回是否成功"""
    cmd = [
        SEVENZIP, "x",
        str(archive),
        f"-p{password}",
        f"-o{archive.parent}",
        "-aoa",   # 自动覆盖已存在文件
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # 7z 返回码 0 = 成功，1 = 警告（部分成功），其余为失败
    return result.returncode in (0, 1)


def process_archive(archive: Path) -> str:
    """
    处理单个压缩包，返回状态字符串：
      'ok'       解压成功
      'no_pwd'   文件名中没有数字
      'failed'   解压失败（密码错误或文件损坏）
      'skipped'  不支持的格式
    """
    suffix = archive.suffix.lower()
    if suffix not in ARCHIVE_SUFFIXES:
        return "skipped"

    password = extract_password(archive.stem)
    if not password:
        return "no_pwd"

    # .zip 优先用内置库（无需安装 7-Zip）
    if suffix == ".zip":
        ok = extract_with_zipfile(archive, password)
        if not ok:
            # 回退到 7-Zip（内置库偶尔兼容性差）
            ok = extract_with_7zip(archive, password)
    else:
        ok = extract_with_7zip(archive, password)

    return "ok" if ok else "failed"


def main():
    archives = sorted(
        f for f in DOWNLOAD_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in ARCHIVE_SUFFIXES
    )

    if not archives:
        print(f"目录中没有找到压缩包：{DOWNLOAD_DIR}")
        return

    print(f"共找到 {len(archives)} 个压缩包，开始解压...\n")

    ok_list      = []
    failed_list  = []
    no_pwd_list  = []

    for i, archive in enumerate(archives, 1):
        password = extract_password(archive.stem)
        pwd_display = password if password else "（无数字）"
        print(f"[{i:>4}/{len(archives)}] {archive.name}  密码: {pwd_display}", end="  ")

        status = process_archive(archive)

        if status == "ok":
            print("[OK] 解压成功")
            ok_list.append(archive.name)
        elif status == "failed":
            print("[FAIL] 解压失败（密码错误或文件损坏）")
            failed_list.append(archive.name)
        elif status == "no_pwd":
            print("[WARN] 跳过（文件名中无数字）")
            no_pwd_list.append(archive.name)
        else:
            print("— 跳过（不支持的格式）")

    print(f"\n── 完成 ──")
    print(f"  成功: {len(ok_list)} 个")
    print(f"  失败: {len(failed_list)} 个")
    if failed_list:
        for name in failed_list:
            print(f"    · {name}")
    print(f"  跳过: {len(no_pwd_list)} 个")


if __name__ == "__main__":
    main()
