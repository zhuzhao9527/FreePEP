"""
人教社电子教材全量多线程下载器 (download_all.py)
功能：
按「学段 ➔ 年级」两层层级目录结构，多线程并发下载全网人教社电子教材并自动合成为高清 PDF。

默认目录结构示例：
downloads/
  ├── 小学（六三学制）/
  │     ├── 一年级/
  │     │     ├── 义务教育教科书 语文 一年级 上册.pdf
  │     │     └── 义务教育教科书 数学 一年级 上册.pdf
  │     └── 二年级/
  ├── 初中（六三学制）/
  └── 高中/
        └── 必修/

特性：
- 默认 3 线程并发加速下载（支持 --workers 自定义）
- 自动按「学段/年级」两层文件夹分类存放
- 紧凑输出：不显示单页下载细节，下载并合成完毕时直接提示
- 支持断点续传：已下载完成的教材自动秒跳过，无缝继续
- 自动清理单页切片图片缓存，极大节省磁盘空间
"""

import os
import sys
import re
import time
import random
import argparse
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from pep_core import PepCatalog, PepDownloader, normalize_xd, get_base_dir

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def sanitize_filename(name: str) -> str:
    """过滤文件名中的非法字符"""
    return re.sub(r'[\/:*?"<>|]', '_', name).strip()


def is_match_xd(b_xd: str, b_xdtype: str, target_xds: List[str]) -> bool:
    """判断教材学段是否与目标学段过滤条件匹配"""
    if not target_xds:
        return True
    for t in target_xds:
        # 精确匹配或关键词包含匹配（如匹配 六三、五四、高中）
        if t == b_xd or t == b_xdtype:
            return True
        if ("六三" in t and "六三" in b_xdtype) or ("六三" in t and "六三" in b_xd):
            return True
        if ("五四" in t or "五·四" in t) and ("五四" in b_xdtype or "五·四" in b_xdtype or "五四" in b_xd or "五·四" in b_xd):
            return True
        if ("高中" in t) and ("高中" in b_xd or "高中" in b_xdtype):
            return True
    return False


def run_download_all(output_dir: str = "./downloads",
                     target_xd: str = None,
                     target_nj: str = None,
                     max_workers: int = 3,
                     delay: float = 1.0,
                     clean_temp: bool = True,
                     high_res: bool = False):
    print("=" * 70)
    print("      📚 人民教育出版社 (PEP) 全量教材多线程层级下载器")
    print("=" * 70)

    # 1. 获取全量教材目录数据
    print("[*] 正在加载教材全量目录数据...")
    all_books = PepCatalog.fetch_and_decrypt_all()
    print(f"[+] 成功获取全量教材数据库，共 {len(all_books)} 本。")

    # 2. 条件过滤（支持多个学段，逗号分隔，如："义务教育（六三学制）,义务教育（五四学制）,高中"）
    target_xds = []
    if target_xd and target_xd != "全部":
        target_xds = [x.strip() for x in re.split(r'[,，|/]', target_xd) if x.strip()]

    books_to_download = []
    for b in all_books:
        xd = normalize_xd(b.get("xd", "其他学段"))
        xdtype = b.get("xdtype", "").strip()
        nj = (b.get("nj") or "通用").strip() or "通用"
        
        if not is_match_xd(xd, xdtype, target_xds):
            continue
        if target_nj and target_nj != "全部" and nj != target_nj:
            continue
        books_to_download.append(b)

    total_count = len(books_to_download)
    if total_count == 0:
        print("[-] 未查找到符合条件的教材！请检查学段或年级名称是否正确。")
        return

    base_out = os.path.abspath(output_dir) if output_dir else os.path.join(get_base_dir(), "downloads")
    print(f"\n📂 基础保存目录: {base_out}")
    print(f"📦 待处理教材数量: {total_count} 本")
    print(f"🚀 并发下载线程数: {max_workers} 个线程")
    print(f"🌲 归档目录结构: {base_out}/<学段>/<年级>/<教材名>.pdf")
    print(f"⚡ 断点续传机制: 开启 (已存在 PDF 自动秒跳过)")
    print(f"🧹 切片缓存清理: {'开启 (每本合成后自动删除临时图片)' if clean_temp else '关闭'}")
    print("-" * 70 + "\n")

    downloader = PepDownloader(headless=True, output_dir=base_out)

    # 统计锁
    lock = threading.Lock()
    processed_count = 0
    success_count = 0
    skipped_count = 0
    failed_count = 0
    start_time = time.time()

    def process_single_book(item):
        nonlocal processed_count, success_count, skipped_count, failed_count
        idx, b = item
        book_id = b.get("id")
        raw_title = b.get("title", f"book_{book_id}")
        
        # 优先采用用户习惯的学段规范大类
        xdtype = b.get("xdtype", "").strip()
        xd = normalize_xd(b.get("xd", "其他学段"))
        if "六三" in xdtype:
            stage_dir_name = "义务教育（六三学制）"
        elif "五四" in xdtype or "五·四" in xdtype:
            stage_dir_name = "义务教育（五四学制）"
        elif "高中" in xdtype or "高中" in xd:
            stage_dir_name = "高中"
        else:
            stage_dir_name = xd

        nj = (b.get("nj") or "通用").strip() or "通用"

        safe_xd = sanitize_filename(stage_dir_name)
        safe_nj = sanitize_filename(nj)
        sub_dir = os.path.join(safe_xd, safe_nj)
        safe_title = sanitize_filename(raw_title)

        target_dir = os.path.join(base_out, sub_dir)
        expected_pdf = os.path.join(target_dir, f"{safe_title}.pdf")

        # 检查是否已存在完整 PDF
        if os.path.exists(expected_pdf) and os.path.getsize(expected_pdf) > 50000:
            with lock:
                processed_count += 1
                skipped_count += 1
                percent = (processed_count / total_count) * 100
                size_kb = os.path.getsize(expected_pdf) // 1024
                print(f"[{processed_count}/{total_count}] ({percent:5.1f}%) [✔ 已存在跳过] [{safe_xd}/{safe_nj}] 《{safe_title}》 ({size_kb} KB)")
            return True

        # 开始下载
        try:
            # 错峰启动微延时
            time.sleep(random.uniform(0.1, 0.8))
            
            pdf_path = downloader.download_book(
                book_id=book_id,
                custom_title=raw_title,
                sub_dir=sub_dir,
                skip_if_exists=True,
                clean_temp=clean_temp,
                quiet=True,
                high_res=high_res
            )

            with lock:
                processed_count += 1
                percent = (processed_count / total_count) * 100
                if pdf_path and os.path.exists(pdf_path):
                    success_count += 1
                    pdf_size_mb = round(os.path.getsize(pdf_path) / (1024 * 1024), 2)
                    print(f"[{processed_count}/{total_count}] ({percent:5.1f}%) [🎉 下载合成完成] [{safe_xd}/{safe_nj}] 《{safe_title}》 ({pdf_size_mb} MB)")
                else:
                    failed_count += 1
                    print(f"[{processed_count}/{total_count}] ({percent:5.1f}%) [❌ 下载失败] [{safe_xd}/{safe_nj}] 《{safe_title}》")

            if delay > 0:
                time.sleep(random.uniform(delay * 0.7, delay * 1.3))
            return True
        except Exception as e:
            with lock:
                processed_count += 1
                failed_count += 1
                percent = (processed_count / total_count) * 100
                print(f"[{processed_count}/{total_count}] ({percent:5.1f}%) [❌ 下载异常: {e}] [{safe_xd}/{safe_nj}] 《{safe_title}》")
            return False

    indexed_books = list(enumerate(books_to_download, 1))

    # 使用线程池并发下载
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_single_book, item) for item in indexed_books]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

    elapsed = time.time() - start_time
    elapsed_min = round(elapsed / 60, 1)

    print("\n" + "=" * 70)
    print("🎉 批量下载任务执行完毕！")
    print(f"📊 统计汇总: 总计 {total_count} 本 | 新下载完成 {success_count} 本 | 已存在跳过 {skipped_count} 本 | 失败 {failed_count} 本")
    print(f"⏱️ 总耗时: {elapsed_min} 分钟")
    print(f"📁 教材归档存放于: {base_out}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="人教社电子教材按「学段/年级」层级目录多线程全量下载工具")
    parser.add_argument("--workers", "-w", type=int, default=3, help="同时下载的并发线程数 (默认: 3)")
    parser.add_argument("--output", "-o", default="./downloads", help="PDF 根输出目录 (默认: ./downloads)")
    parser.add_argument("--xd", help="只下载指定学段（如：小学（六三学制）、初中（六三学制）、高中 等）")
    parser.add_argument("--nj", help="只下载指定年级（如：一年级、七年级 等）")
    parser.add_argument("--delay", "-d", type=float, default=0.5, help="单线程任务间休眠秒数 (默认: 0.5 秒)")
    parser.add_argument("--high-res", "--hd", action="store_true", help="下载高清大图版本 (large)，默认普通版本 (mobile)")
    parser.add_argument("--keep-temp", action="store_true", help="保留单页切片图片缓存（默认会自动删除以节约空间）")

    args = parser.parse_args()

    run_download_all(
        output_dir=args.output,
        target_xd=args.xd,
        target_nj=args.nj,
        max_workers=args.workers,
        delay=args.delay,
        clean_temp=not args.keep_temp,
        high_res=args.high_res
    )


if __name__ == "__main__":
    main()
