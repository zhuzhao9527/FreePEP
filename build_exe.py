"""
FreePEP 一键打包分发脚本 (build_exe.py)
功能：
1. 检查并自动安装 PyInstaller
2. 打包 WebUI 为独立可执行文件 FreePEP.exe
3. 自动抓取并内嵌 Chromium 便携版浏览器内核至 dist/FreePEP/browsers/
4. 生成开箱即用的完全独立便携版压缩包 (FreePEP-Windows-x64.zip)
"""

import os
import sys
import shutil
import zipfile
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def check_and_install_pyinstaller():
    """检查 PyInstaller 是否已安装，未安装则自动安装"""
    try:
        import PyInstaller
        print("[+] 检测到 PyInstaller 已安装。")
    except ImportError:
        print("[*] 未检测到 PyInstaller，正在通过 pip 自动安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[+] PyInstaller 安装完成！")


def find_playwright_browsers_dir():
    """定位本机 Playwright 下载的浏览器内核路径"""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    ms_playwright = os.path.join(local_app_data, "ms-playwright")
    if os.path.exists(ms_playwright):
        return ms_playwright
    return None


def build_package():
    print("=" * 65)
    print("       🚀 FreePEP 独立 EXE 便携发行包打包脚本")
    print("=" * 65)

    check_and_install_pyinstaller()

    dist_dir = os.path.abspath("./dist")
    build_dir = os.path.abspath("./build")
    out_app_dir = os.path.join(dist_dir, "FreePEP")

    # 清理旧的编译产物
    if os.path.exists(out_app_dir):
        print(f"[*] 清理旧输出目录: {out_app_dir}")
        shutil.rmtree(out_app_dir, ignore_errors=True)

    # 1. 组装 PyInstaller 命令
    print("\n[1/3] 正在使用 PyInstaller 编译 Python 代码与依赖...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=FreePEP",
        "--onedir",                       # 目录模式（比单文件解压更快、更利于内嵌浏览器）
        "--collect-all=playwright",        # 打包 playwright driver 与所有依赖
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespans",
        "--hidden-import=uvicorn.lifespans.on",
        "--clean",
        "-y",
        "webui.py"
    ]

    subprocess.check_call(cmd)
    print("[+] 核心程序 FreePEP.exe 编译成功！")

    # 2. 拷贝 Playwright Chromium 绿色便携浏览器到目标目录
    print("\n[2/3] 正在打包绿色便携版 Chromium 浏览器内核...")
    pw_src = find_playwright_browsers_dir()
    target_browsers_dir = os.path.join(out_app_dir, "_internal", "browsers")
    target_browsers_dir2 = os.path.join(out_app_dir, "browsers")

    if pw_src:
        print(f"[*] 从本机提取 Chromium 内核: {pw_src}")
        os.makedirs(target_browsers_dir2, exist_ok=True)
        for item in os.listdir(pw_src):
            if "chromium" in item.lower() or "ffmpeg" in item.lower():
                s_path = os.path.join(pw_src, item)
                d_path = os.path.join(target_browsers_dir2, item)
                if not os.path.exists(d_path):
                    print(f"    -> 拷贝内核组件: {item}")
                    if os.path.isdir(s_path):
                        shutil.copytree(s_path, d_path)
                    else:
                        shutil.copy2(s_path, d_path)
        print("[+] 便携浏览器内核内嵌完成！分发给用户无需安装任何浏览器或 Python。")
    else:
        print("[!] 警告: 本机未找到 Playwright 缓存的 Chromium，建议先运行 'playwright install chromium'。")

    # 拷贝默认说明和依赖
    for f in ["README.md", "pep_catalog.json"]:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(out_app_dir, f))

    # 3. 压缩为发布 ZIP 包
    print("\n[3/3] 正在生成发布压缩包...")
    zip_name = "FreePEP-Windows-x64.zip"
    zip_path = os.path.join(dist_dir, zip_name)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(out_app_dir):
            for file in files:
                abs_f = os.path.join(root, file)
                rel_f = os.path.relpath(abs_f, dist_dir)
                zipf.write(abs_f, rel_f)

    zip_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
    print("\n" + "=" * 65)
    print(f"🎉 打包全部完成！")
    print(f"📁 绿色便携文件夹: {out_app_dir}")
    print(f"📦 最终分发压缩包: {zip_path} ({zip_size_mb} MB)")
    print("=" * 65)
    print("\n👉 分发使用说明：")
    print("   直接将 FreePEP-Windows-x64.zip 发送给用户即可。")
    print("   用户解压后双击 FreePEP.exe，无需配置 Python，会自动弹出浏览器打开页面！\n")


if __name__ == "__main__":
    build_package()
