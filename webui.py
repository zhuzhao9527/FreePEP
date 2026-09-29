"""
人教社电子教材 WebUI 管理与下载系统 (webui.py)
基于 FastAPI + TailwindCSS 构建，提供与原版网站一致的可视化筛选与一键批量下载体验。
"""

import os
import sys
import time
import json
import asyncio
import webbrowser
import threading
from typing import List, Dict, Optional
from pydantic import BaseModel
import uvicorn
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pep_core import PepCatalog, PepDownloader, XD_ORDER, XK_ORDER_PREFIX, NJ_ORDER, get_base_dir, normalize_xd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="人教社电子教材下载器")

DOWNLOAD_DIR = os.path.join(get_base_dir(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 页内阅读切片静态服务目录
TEMP_PAGES_DIR = os.path.join(get_base_dir(), "temp_pages")
os.makedirs(TEMP_PAGES_DIR, exist_ok=True)
app.mount("/temp_pages", StaticFiles(directory=TEMP_PAGES_DIR), name="temp_pages")

# 全局任务状态管理
class TaskManager:
    def __init__(self):
        self.queue: List[Dict] = []
        self.is_running = False
        self.current_book: Optional[Dict] = None
        self.current_page = 0
        self.total_pages = 0
        self.status_text = "空闲中"
        self.logs: List[str] = []
        self._lock = threading.Lock()

    def log(self, text: str):
        with self._lock:
            self.logs.append(text)
            if len(self.logs) > 500:
                self.logs.pop(0)

    def get_status(self) -> Dict:
        with self._lock:
            return {
                "is_running": self.is_running,
                "queue_len": len(self.queue),
                "current_book": self.current_book,
                "current_page": self.current_page,
                "total_pages": self.total_pages,
                "progress_percent": int((self.current_page / self.total_pages * 100)) if self.total_pages > 0 else 0,
                "status_text": self.status_text,
                "recent_logs": self.logs[-25:]
            }

    def add_tasks(self, books: List[Dict], high_res: bool = False):
        with self._lock:
            existing_ids = {b["id"] for b in self.queue}
            if self.current_book:
                existing_ids.add(self.current_book["id"])
            for b in books:
                if b["id"] not in existing_ids:
                    item = dict(b)
                    item["_high_res"] = high_res
                    self.queue.append(item)
                    existing_ids.add(b["id"])
        quality_str = "高清模式" if high_res else "普通模式"
        self.log(f"[*] 已添加 {len(books)} 本教材至下载队列 ({quality_str})。")

    def run_worker(self):
        """后台单线程顺序执行下载队列中的教材"""
        downloader = PepDownloader(headless=True, output_dir=DOWNLOAD_DIR)
        
        while True:
            book_to_download = None
            with self._lock:
                if self.queue:
                    book_to_download = self.queue.pop(0)
                    self.current_book = book_to_download
                    self.is_running = True
                    self.current_page = 0
                    self.total_pages = 0
                    self.status_text = f"正在准备下载《{book_to_download.get('title')}》..."
                else:
                    self.current_book = None
                    self.is_running = False
                    self.current_page = 0
                    self.total_pages = 0
                    self.status_text = "所有任务已完成"

            if not book_to_download:
                time.sleep(1)
                continue

            def progress_callback(cur, total, txt):
                with self._lock:
                    self.current_page = cur
                    self.total_pages = total
                    self.status_text = txt

            def log_callback(txt):
                self.log(txt)

            try:
                import re
                xd = normalize_xd(book_to_download.get("xd", "其他学段"))
                nj = (book_to_download.get("nj") or "通用").strip() or "通用"
                safe_xd = re.sub(r'[\/:*?"<>|]', '_', xd).strip()
                safe_nj = re.sub(r'[\/:*?"<>|]', '_', nj).strip()
                sub_dir = os.path.join(safe_xd, safe_nj)
                is_high_res = book_to_download.get("_high_res", False)

                self.log(f"==================================================")
                self.log(f"[*] 开始下载教材: [{safe_xd}/{safe_nj}] 《{book_to_download.get('title')}》 ({'高清版' if is_high_res else '普通版'})")
                downloader.download_book(
                    book_id=book_to_download["id"],
                    custom_title=book_to_download.get("title"),
                    sub_dir=sub_dir,
                    progress_cb=progress_callback,
                    log_cb=log_callback,
                    skip_if_exists=True,
                    clean_temp=True,
                    high_res=is_high_res
                )
            except Exception as e:
                self.log(f"[-] 下载异常: {e}")

            time.sleep(1)


task_manager = TaskManager()

# 启动后台下载线程
worker_thread = threading.Thread(target=task_manager.run_worker, daemon=True)
worker_thread.start()


class FilterQuery(BaseModel):
    xd: Optional[str] = "全部"
    xk: Optional[str] = "全部"
    nj: Optional[str] = "全部"
    keyword: Optional[str] = ""


class BatchDownloadRequest(BaseModel):
    book_ids: List[str]
    high_res: Optional[bool] = False


@app.get("/api/structure")
def get_structure():
    """获取所有学段、学科、年级的结构（保持严格定制排序）"""
    return PepCatalog.get_structure()


@app.post("/api/books")
def list_books(query: FilterQuery):
    """根据条件筛选教材列表"""
    books = PepCatalog.filter_books(
        xd=query.xd,
        xk=query.xk,
        nj=query.nj,
        keyword=query.keyword
    )
    return {"total": len(books), "books": books}


@app.get("/api/status")
def get_download_status():
    """轮询当前下载状态"""
    return task_manager.get_status()


@app.post("/api/download")
def add_download(req: BatchDownloadRequest):
    """提交下载请求"""
    all_books = {b["id"]: b for b in PepCatalog.fetch_and_decrypt_all()}
    selected = [all_books[bid] for bid in req.book_ids if bid in all_books]
    if selected:
        task_manager.add_tasks(selected, high_res=bool(req.high_res))
    return {"status": "ok", "added_count": len(selected)}


@app.post("/api/refresh_catalog")
def refresh_catalog():
    """强制重新从官方服务器拉取并解密最新教材目录"""
    try:
        books = PepCatalog.fetch_and_decrypt_all(force_refresh=True)
        return {"status": "ok", "total": len(books)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/clear_cache")
def clear_cache():
    """清理本地临时缓存图片"""
    try:
        res = PepCatalog.clear_cache_files()
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/open_folder")
def open_download_folder():
    """在资源管理器中打开下载文件夹"""
    try:
        if sys.platform == "win32":
            os.startfile(DOWNLOAD_DIR)
        elif sys.platform == "darwin":
            os.system(f'open "{DOWNLOAD_DIR}"')
        else:
            os.system(f'xdg-open "{DOWNLOAD_DIR}"')
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 页内阅读器：正在准备的教材集合（防止同一本书并发重复拉取）
_reader_preparing = set()
_reader_preparing_lock = threading.Lock()


def _list_reader_pages(book_id: str, res_type: str = "mobile"):
    """列出某本书已缓存的切片页面 URL（按页码排序）"""
    book_dir = os.path.join(TEMP_PAGES_DIR, f"{book_id}_{res_type}")
    if not os.path.isdir(book_dir):
        return []
    pages = []
    for name in os.listdir(book_dir):
        if name.lower().endswith(".jpg") and name.split(".")[0].isdigit():
            pages.append((int(name.split(".")[0]), name))
    pages.sort()
    return [f"/temp_pages/{book_id}_{res_type}/{name}" for _, name in pages]


@app.get("/api/reader/prepare/{book_id}")
def reader_prepare(book_id: str):
    """准备页内阅读切片：有缓存直接返回，无缓存则通过 Playwright 过盾拉取"""
    book = next((b for b in PepCatalog.fetch_and_decrypt_all() if b["id"] == book_id), None)
    if not book:
        return {"status": "error", "message": "教材目录中未找到该书"}

    cached = _list_reader_pages(book_id)
    if cached:
        return {"status": "ok", "cached": True, "pages": cached}

    with _reader_preparing_lock:
        if book_id in _reader_preparing:
            return {"status": "preparing", "message": "该书切片正在准备中，请稍后重试"}
        _reader_preparing.add(book_id)
    try:
        downloader = PepDownloader(headless=True, output_dir=DOWNLOAD_DIR)
        downloader.download_book(
            book_id=book_id,
            custom_title=book.get("title"),
            sub_dir=os.path.join("reader_cache", book_id),
            quiet=True,
            clean_temp=False,
            compose_pdf=False
        )
    except Exception as e:
        return {"status": "error", "message": f"切片拉取异常: {e}"}
    finally:
        with _reader_preparing_lock:
            _reader_preparing.discard(book_id)

    pages = _list_reader_pages(book_id)
    if not pages:
        return {"status": "error", "message": "切片拉取失败，请稍后重试"}
    return {"status": "ok", "cached": False, "pages": pages}


@app.get("/", response_class=HTMLResponse)
def index_page():
    """返回一体化前端页面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="referrer" content="no-referrer">
    <title>人教社电子教材下载器</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: #f1f5f9; }
        /* Toast 通知 */
        #toastContainer {
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 100;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            pointer-events: none;
        }
        .toast-item {
            pointer-events: auto;
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
            min-width: 260px;
            max-width: 360px;
            background: #fff;
            border: 1px solid #e2e8f0;
            border-left-width: 4px;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
            padding: 0.75rem 1rem;
            font-size: 13px;
            color: #1e293b;
            animation: toastIn 0.25s ease-out;
        }
        .toast-item.toast-out { animation: toastOut 0.2s ease-in forwards; }
        .toast-item.success { border-left-color: #16a34a; }
        .toast-item.error { border-left-color: #dc2626; }
        .toast-item.info { border-left-color: #2563eb; }
        .toast-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
        .toast-item.success .toast-dot { background: #16a34a; }
        .toast-item.error .toast-dot { background: #dc2626; }
        .toast-item.info .toast-dot { background: #2563eb; }
        @keyframes toastIn { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes toastOut { from { opacity: 1; } to { opacity: 0; transform: translateY(-8px); } }

        /* 模态确认框 */
        .modal-mask {
            position: fixed;
            inset: 0;
            z-index: 110;
            background: rgba(15, 23, 42, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            animation: fadeIn 0.15s ease-out;
        }
        .modal-card {
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
            width: 360px;
            max-width: calc(100vw - 2rem);
            padding: 1.25rem 1.5rem;
            animation: modalIn 0.18s ease-out;
        }
        .modal-title { font-size: 15px; font-weight: 600; color: #0f172a; margin-bottom: 0.5rem; }
        .modal-message { font-size: 13px; color: #475569; line-height: 1.6; white-space: pre-line; }
        .modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1.25rem; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes modalIn { from { opacity: 0; transform: scale(0.95) translateY(8px); } to { opacity: 1; transform: scale(1) translateY(0); } }

        /* 页内阅读器 */
        .reader-mask {
            position: fixed;
            inset: 0;
            z-index: 120;
            background: rgba(15, 23, 42, 0.6);
            display: flex;
            align-items: center;
            justify-content: center;
            animation: fadeIn 0.15s ease-out;
        }
        .reader-card {
            width: min(1100px, 94vw);
            height: 92vh;
            background: #fff;
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 50px rgba(15, 23, 42, 0.3);
            animation: modalIn 0.18s ease-out;
        }
        .reader-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.65rem 1rem;
            border-bottom: 1px solid #e2e8f0;
            flex-shrink: 0;
        }
        .reader-title { font-size: 14px; font-weight: 600; color: #0f172a; }
        .reader-btn {
            font-size: 12px;
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
            background: #f1f5f9;
            color: #334155;
            transition: background 0.15s;
        }
        .reader-btn:hover { background: #e2e8f0; }
        .reader-close { background: #2563eb; color: #fff; }
        .reader-close:hover { background: #1d4ed8; }
        .reader-frame { flex: 1; width: 100%; border: 0; background: #f8fafc; }
        .reader-scroll { overflow-y: auto; }
        .reader-loading { padding: 3rem 1rem; text-align: center; color: #64748b; font-size: 13px; }
        .reader-page { display: block; width: min(720px, 92%); margin: 12px auto; background: #fff; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12); }

        /* 封面大图预览 */
        .imgpreview-mask {
            position: fixed;
            inset: 0;
            z-index: 130;
            background: rgba(15, 23, 42, 0.78);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            cursor: zoom-out;
            animation: fadeIn 0.15s ease-out;
        }
        .imgpreview-img {
            max-width: 90vw;
            max-height: 80vh;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            background: #fff;
        }
        .imgpreview-title {
            margin-top: 1rem;
            font-size: 14px;
            font-weight: 500;
            color: #e2e8f0;
            text-align: center;
            max-width: 80vw;
        }
    </style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen flex flex-col font-sans">
    
    <!-- 顶部导航栏 -->
    <header class="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div>
                <h1 class="text-lg font-bold text-slate-900 leading-tight">人教社电子教材下载器</h1>
                <p class="text-xs text-slate-500">无需验证码 · 教材批量检索 · 一键合成高清 PDF</p>
            </div>
            
            <div class="flex items-center space-x-2">
                <button onclick="clearCache()" id="clearCacheBtn" class="px-3 py-1.5 text-xs font-medium bg-red-50 hover:bg-red-100 text-red-700 rounded-md transition flex items-center space-x-1 border border-red-200" title="删除临时页面下载缓存">
                    <span>清理缓存</span>
                </button>
                <button onclick="refreshCatalog()" id="refreshBtn" class="px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md transition flex items-center space-x-1 border border-slate-300">
                    <span>同步最新目录</span>
                </button>
                <button onclick="openDownloadFolder()" class="px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md transition flex items-center space-x-1 border border-slate-300">
                    <span>打开保存目录</span>
                </button>
            </div>
        </div>
    </header>

    <!-- 主体区域 -->
    <main class="max-w-7xl mx-auto px-4 py-6 flex-1 w-full space-y-6">
        
        <!-- 任务进度横幅 (有任务时显示) -->
        <div id="progressBanner" class="bg-white border border-blue-200 rounded-xl p-4 shadow-sm space-y-3">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span id="spinner" class="animate-spin text-blue-600 text-lg hidden">⚙️</span>
                    <span class="text-sm font-semibold text-slate-800" id="currentTaskTitle">当前状态: 空闲中</span>
                </div>
                <div class="text-xs text-slate-500">
                    队列等待: <span id="queueCount" class="font-bold text-blue-600">0</span> 本
                </div>
            </div>
            
            <div class="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
                <div id="progressBar" class="bg-blue-600 h-2.5 rounded-full transition-all duration-300" style="width: 0%"></div>
            </div>
            
            <div class="flex justify-between text-xs text-slate-500">
                <span id="statusDetail">就绪</span>
                <span id="progressPercent">0%</span>
            </div>
        </div>

        <!-- 筛选与搜索卡片 -->
        <div class="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
            
            <!-- 搜索框 -->
            <div class="relative">
                <input type="text" id="searchInput" placeholder="全局搜索教材（例如：必修一、高一语文、道德与法治...）"
                       class="w-full px-4 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                       oninput="onSearchChange()">
            </div>

            <!-- 筛选条件折叠开关 -->
            <div class="flex items-center justify-between cursor-pointer select-none" onclick="toggleFilterPanel()">
                <span class="text-sm font-semibold text-slate-700">筛选条件</span>
                <span id="filterToggle" class="text-xs text-blue-600 font-medium">收起 ▲</span>
            </div>

            <div id="filterBody" class="space-y-4">
                <!-- 学段过滤 -->
                <div class="flex items-start space-x-2">
                    <span class="text-xs font-semibold text-slate-500 whitespace-nowrap pt-1.5 w-14">学段：</span>
                    <div id="xdPills" class="flex flex-wrap gap-1.5">
                        <button class="pill-btn active px-3 py-1 text-xs rounded-md bg-blue-600 text-white" onclick="selectXd('全部')">全部</button>
                    </div>
                </div>

                <!-- 学科过滤 -->
                <div class="flex items-start space-x-2 border-t border-slate-100 pt-3">
                    <span class="text-xs font-semibold text-slate-500 whitespace-nowrap pt-1.5 w-14">学科：</span>
                    <div id="xkPills" class="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto custom-scrollbar">
                        <button class="pill-btn active px-3 py-1 text-xs rounded-md bg-blue-600 text-white" onclick="selectXk('全部')">全部</button>
                    </div>
                </div>

                <!-- 年级过滤 -->
                <div class="flex items-start space-x-2 border-t border-slate-100 pt-3">
                    <span class="text-xs font-semibold text-slate-500 whitespace-nowrap pt-1.5 w-14">年级：</span>
                    <div id="njPills" class="flex flex-wrap gap-1.5">
                        <button class="pill-btn active px-3 py-1 text-xs rounded-md bg-blue-600 text-white" onclick="selectNj('全部')">全部</button>
                    </div>
                </div>
            </div>

        </div>

        <!-- 操作与教材列表 -->
        <div class="space-y-4">
            
            <!-- 批量操作条 -->
            <div class="flex flex-wrap items-center justify-between gap-3 bg-white border border-slate-200 px-4 py-3 rounded-lg text-xs">
                <div class="flex items-center space-x-4">
                    <label class="flex items-center space-x-2 cursor-pointer select-none">
                        <input type="checkbox" id="selectAllCheckbox" onchange="toggleSelectAll()" class="rounded text-blue-600 focus:ring-blue-500">
                        <span class="font-medium text-slate-700">全选当前筛选</span>
                    </label>
                    <span class="text-slate-500">已找到 <b id="totalBooksCount" class="text-slate-900">0</b> 本教材</span>
                    <span class="text-slate-500">已选中 <b id="selectedCount" class="text-blue-600">0</b> 本</span>
                </div>
                
                <div class="flex items-center space-x-3">
                    <label class="flex items-center space-x-1.5 cursor-pointer select-none bg-slate-50 hover:bg-slate-100 border border-slate-200 px-2.5 py-1 rounded text-slate-700 font-medium transition" title="开启后将抓取 large 高清切片原图（若该教材无高清原图则自动降级为普通版）">
                        <input type="checkbox" id="highResToggle" class="rounded text-blue-600 focus:ring-blue-500">
                        <span>下载高清原图版本 (large)</span>
                    </label>
                    <button onclick="downloadSelected()" id="batchBtn" disabled
                            class="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-medium rounded-md shadow-sm transition flex items-center space-x-1.5">
                        <span>一键批量下载已选教材</span>
                    </button>
                </div>
            </div>

            <!-- 教材卡片网格（限高区域，内部滚动） -->
            <div id="bookGrid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 overflow-y-auto custom-scrollbar">
                <!-- 动态填充卡片 -->
            </div>

            <!-- 分页控件 -->
            <div id="paginationBar" class="flex flex-wrap items-center justify-between gap-2 text-xs"></div>

        </div>

    </main>

    <script>
        let structure = {};
        let currentXd = "全部";
        let currentXk = "全部";
        let currentNj = "全部";
        let currentSearch = "";
        let currentBooks = [];
        let selectedBookIds = new Set();
        let currentPage = 1;
        let pageSize = 20;

        // 页面初始化
        async function init() {
            const res = await fetch('/api/structure');
            structure = await res.json();
            renderFilters();
            await fetchBooks();
            setInterval(pollStatus, 1500);
        }

        function renderFilters() {
            // 渲染学段（后端已严格按规定排序）
            const xdContainer = document.getElementById('xdPills');
            const xds = ["全部", ...Object.keys(structure)];
            xdContainer.innerHTML = xds.map(xd => `
                <button onclick="selectXd('${xd}')" class="pill-xd px-2.5 py-1 text-xs rounded-md border transition ${xd === currentXd ? 'bg-blue-600 border-blue-600 text-white font-medium' : 'bg-slate-100 hover:bg-slate-200 border-slate-200 text-slate-700'}">${xd}</button>
            `).join('');

            // 渲染学科（后端已按规定排序：语文、数学、英语...）
            const xkContainer = document.getElementById('xkPills');
            let subjects = [];
            if (currentXd === "全部") {
                const sSet = new Set();
                Object.values(structure).forEach(item => item.subjects.forEach(s => sSet.add(s)));
                // 保持学科定制优先排序
                const orderPrefix = ['语文', '数学', '英语', '物理', '化学', '历史', '思想政治', '地理', '生物学', '音乐', '道德与法治'];
                subjects = ["全部", ...Array.from(sSet).sort((a, b) => {
                    const ia = orderPrefix.indexOf(a);
                    const ib = orderPrefix.indexOf(b);
                    if (ia !== -1 && ib !== -1) return ia - ib;
                    if (ia !== -1) return -1;
                    if (ib !== -1) return 1;
                    return a.localeCompare(b, 'zh');
                })];
            } else {
                subjects = ["全部", ...(structure[currentXd]?.subjects || [])];
            }
            xkContainer.innerHTML = subjects.map(xk => `
                <button onclick="selectXk('${xk}')" class="pill-xk px-2.5 py-1 text-xs rounded-md border transition ${xk === currentXk ? 'bg-blue-600 border-blue-600 text-white font-medium' : 'bg-slate-100 hover:bg-slate-200 border-slate-200 text-slate-700'}">${xk}</button>
            `).join('');

            // 渲染年级（后端已按规定排序：一年级、二年级...）
            const njContainer = document.getElementById('njPills');
            let grades = [];
            if (currentXd === "全部") {
                const gSet = new Set();
                Object.values(structure).forEach(item => item.grades.forEach(g => gSet.add(g)));
                const orderNj = ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级', '七年级', '八年级', '九年级', '三年级;四年级', '五年级;六年级', '专项', '必修', '选择性必修'];
                grades = ["全部", ...Array.from(gSet).sort((a, b) => {
                    const ia = orderNj.indexOf(a);
                    const ib = orderNj.indexOf(b);
                    if (ia !== -1 && ib !== -1) return ia - ib;
                    if (ia !== -1) return -1;
                    if (ib !== -1) return 1;
                    return a.localeCompare(b, 'zh');
                })];
            } else {
                grades = ["全部", ...(structure[currentXd]?.grades || [])];
            }
            njContainer.innerHTML = grades.map(nj => `
                <button onclick="selectNj('${nj}')" class="pill-nj px-2.5 py-1 text-xs rounded-md border transition ${nj === currentNj ? 'bg-blue-600 border-blue-600 text-white font-medium' : 'bg-slate-100 hover:bg-slate-200 border-slate-200 text-slate-700'}">${nj}</button>
            `).join('');
        }

        async function selectXd(xd) {
            currentXd = xd;
            currentXk = "全部";
            currentNj = "全部";
            renderFilters();
            await fetchBooks();
        }

        async function selectXk(xk) {
            currentXk = xk;
            renderFilters();
            await fetchBooks();
        }

        async function selectNj(nj) {
            currentNj = nj;
            renderFilters();
            await fetchBooks();
        }

        let debounceTimer;
        function onSearchChange() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                currentSearch = document.getElementById('searchInput').value.trim();
                fetchBooks();
            }, 300);
        }

        function toggleFilterPanel() {
            const body = document.getElementById('filterBody');
            const toggle = document.getElementById('filterToggle');
            const isHidden = body.style.display === 'none';
            body.style.display = isHidden ? '' : 'none';
            toggle.textContent = isHidden ? '收起 ▲' : '展开 ▼';
        }

        async function fetchBooks() {
            const res = await fetch('/api/books', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    xd: currentXd,
                    xk: currentXk,
                    nj: currentNj,
                    keyword: currentSearch
                })
            });
            const data = await res.json();
            currentBooks = data.books;
            currentPage = 1;
            document.getElementById('totalBooksCount').innerText = currentBooks.length;
            renderBookGrid();
            updateSelectionUI();
        }

        function renderBookGrid() {
            const grid = document.getElementById('bookGrid');
            if (currentBooks.length === 0) {
                grid.innerHTML = `
                    <div class="col-span-full py-12 text-center text-slate-400 text-sm">
                        没有找到符合条件的教材，请尝试重置筛选条件或更改搜索词。
                    </div>
                `;
                document.getElementById('paginationBar').innerHTML = '';
                grid.style.maxHeight = '';
                return;
            }

            const totalPages = getTotalPages();
            if (currentPage > totalPages) currentPage = totalPages;
            const start = (currentPage - 1) * pageSize;
            const pageBooks = currentBooks.slice(start, start + pageSize);

            grid.innerHTML = pageBooks.map(b => {
                const isSelected = selectedBookIds.has(b.id);
                return `
                <div class="book-card bg-white border ${isSelected ? 'border-blue-500 ring-2 ring-blue-100' : 'border-slate-200'} rounded-lg p-2 shadow-sm hover:shadow-md transition flex flex-col justify-between space-y-2 relative group">

                    <!-- 勾选框 -->
                    <div class="absolute top-2 left-2 z-10">
                        <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleBookSelection('${b.id}')"
                               class="w-3.5 h-3.5 text-blue-600 rounded border-slate-300 focus:ring-blue-500 cursor-pointer">
                    </div>

                    <div class="space-y-1.5">
                        <!-- 封面（居中展示，点击放大预览） -->
                        <div class="flex justify-center">
                            <div class="w-32 aspect-[3/4] bg-slate-100 rounded-md overflow-hidden flex items-center justify-center cursor-zoom-in"
                                 onclick="openImagePreview('${b.thumb || 'https://www.pep.com.cn/images/bg_hp_pep2022.png'}', '${b.title}')" title="点击放大预览">
                                <img src="${b.thumb || 'https://www.pep.com.cn/images/bg_hp_pep2022.png'}"
                                     alt="${b.title}"
                                     class="w-full h-full object-contain pointer-events-none"
                                     onerror="this.onerror=null;this.src='https://jc.pep.com.cn/img/banner_pc.18312502.png'">
                            </div>
                        </div>

                        <!-- 标签 -->
                        <div class="flex flex-wrap gap-1">
                            <span class="px-1 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-medium rounded">${b.xd}</span>
                            <span class="px-1 py-0.5 bg-emerald-50 text-emerald-600 text-[10px] font-medium rounded">${b.xk}</span>
                            <span class="px-1 py-0.5 bg-purple-50 text-purple-600 text-[10px] font-medium rounded">${b.nj}${b.cc || ''}</span>
                        </div>

                        <!-- 标题 -->
                        <h3 class="text-[11px] font-semibold text-slate-800 line-clamp-2 leading-snug" title="${b.title}">
                            ${b.title}
                        </h3>
                    </div>

                    <!-- 操作栏 -->
                    <div class="pt-1.5 border-t border-slate-100 flex items-center justify-between">
                        <button onclick="openReaderModal('${b.id}', '${b.title}')"
                                class="text-[11px] text-slate-500 hover:text-blue-600 transition">
                            在线阅读
                        </button>
                        <button onclick="downloadSingle('${b.id}')"
                                class="px-2 py-0.5 bg-slate-100 hover:bg-blue-600 hover:text-white text-slate-700 text-[11px] font-medium rounded transition">
                            下载 PDF
                        </button>
                    </div>

                </div>
                `;
            }).join('');

            renderPagination();
            applyGridMaxHeight();
        }

        function getTotalPages() {
            return Math.max(1, Math.ceil(currentBooks.length / pageSize));
        }

        function applyGridMaxHeight() {
            const grid = document.getElementById('bookGrid');
            const card = grid.querySelector('.book-card');
            if (!card) { grid.style.maxHeight = ''; return; }
            const gap = 12;
            grid.style.maxHeight = (card.offsetHeight * 3 + gap * 2) + 'px';
        }

        function renderPagination() {
            const bar = document.getElementById('paginationBar');
            const totalPages = getTotalPages();
            let pages = [];
            if (totalPages <= 7) {
                for (let i = 1; i <= totalPages; i++) pages.push(i);
            } else {
                pages.push(1);
                if (currentPage > 3) pages.push('...');
                for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) pages.push(i);
                if (currentPage < totalPages - 2) pages.push('...');
                pages.push(totalPages);
            }
            const pageBtns = pages.map(p => {
                if (p === '...') return '<span class="px-1.5 py-1 text-slate-400">...</span>';
                const cls = p === currentPage
                    ? 'px-2 py-1 rounded bg-blue-600 text-white font-medium'
                    : 'px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700';
                return `<button onclick="goToPage(${p})" class="${cls}">${p}</button>`;
            }).join('');
            bar.innerHTML = `
                <div class="flex items-center space-x-2 text-slate-500">
                    <span>共 <b class="text-slate-900">${currentBooks.length}</b> 本</span>
                    <span>第 ${currentPage} / ${totalPages} 页</span>
                </div>
                <div class="flex items-center space-x-3">
                    <div class="flex items-center space-x-1">
                        <button onclick="goToPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}
                                class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed">上一页</button>
                        ${pageBtns}
                        <button onclick="goToPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}
                                class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 disabled:opacity-40 disabled:cursor-not-allowed">下一页</button>
                    </div>
                    <label class="flex items-center space-x-1 text-slate-500">
                        每页
                        <select onchange="changePageSize(this.value)"
                                class="border border-slate-200 rounded px-1 py-0.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-500">
                            ${[20, 50, 100, 200].map(n => `<option value="${n}" ${n === pageSize ? 'selected' : ''}>${n}</option>`).join('')}
                        </select>
                        条
                    </label>
                </div>
            `;
        }

        function goToPage(p) {
            const totalPages = getTotalPages();
            currentPage = Math.min(Math.max(1, p), totalPages);
            renderBookGrid();
            document.getElementById('bookGrid').scrollTop = 0;
        }

        function changePageSize(v) {
            pageSize = parseInt(v);
            currentPage = 1;
            renderBookGrid();
        }

        function toggleBookSelection(id) {
            if (selectedBookIds.has(id)) selectedBookIds.delete(id);
            else selectedBookIds.add(id);
            renderBookGrid();
            updateSelectionUI();
        }

        function toggleSelectAll() {
            const selectAll = document.getElementById('selectAllCheckbox').checked;
            if (selectAll) {
                currentBooks.forEach(b => selectedBookIds.add(b.id));
            } else {
                currentBooks.forEach(b => selectedBookIds.delete(b.id));
            }
            renderBookGrid();
            updateSelectionUI();
        }

        function updateSelectionUI() {
            const count = selectedBookIds.size;
            document.getElementById('selectedCount').innerText = count;
            document.getElementById('batchBtn').disabled = (count === 0);
            const selectAllCheckbox = document.getElementById('selectAllCheckbox');
            if (currentBooks.length > 0) {
                const allSelected = currentBooks.every(b => selectedBookIds.has(b.id));
                selectAllCheckbox.checked = allSelected;
            } else {
                selectAllCheckbox.checked = false;
            }
        }

        async function downloadSingle(id) {
            const highRes = document.getElementById('highResToggle')?.checked || false;
            await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ book_ids: [id], high_res: highRes })
            });
            pollStatus();
        }

        async function downloadSelected() {
            const ids = Array.from(selectedBookIds);
            if (ids.length === 0) return;
            const highRes = document.getElementById('highResToggle')?.checked || false;
            await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ book_ids: ids, high_res: highRes })
            });
            selectedBookIds.clear();
            updateSelectionUI();
            renderBookGrid();
            pollStatus();
        }

        async function refreshCatalog() {
            const btn = document.getElementById('refreshBtn');
            btn.textContent = '同步中...';
            btn.disabled = true;
            try {
                const res = await fetch('/api/refresh_catalog', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`目录同步成功！共获取到 ${data.total} 本教材`, 'success');
                    await init();
                } else {
                    showToast('同步失败: ' + data.message, 'error', 4500);
                }
            } catch (e) {
                showToast('网络请求异常: ' + e, 'error', 4500);
            } finally {
                btn.textContent = '同步最新目录';
                btn.disabled = false;
            }
        }

        async function clearCache() {
            if (!(await showConfirm('确定要清理本地下载临时缓存（temp_pages）吗？\\n这不会影响已生成的 PDF 文件。', '清理缓存'))) {
                return;
            }
            try {
                const res = await fetch('/api/clear_cache', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(data.message, 'success');
                } else {
                    showToast('清理失败: ' + data.message, 'error', 4500);
                }
            } catch (e) {
                showToast('清理失败: ' + e, 'error', 4500);
            }
        }

        async function openDownloadFolder() {
            await fetch('/api/open_folder', { method: 'POST' });
        }

        async function openReaderModal(bookId, title) {
            if (document.getElementById('readerMask')) return;
            const mask = document.createElement('div');
            mask.id = 'readerMask';
            mask.className = 'reader-mask';
            mask.innerHTML = `
                <div class="reader-card">
                    <div class="reader-header">
                        <span class="reader-title">${title}</span>
                        <div class="flex items-center space-x-2">
                            <button onclick="closeReaderModal()" class="reader-btn reader-close">关闭</button>
                        </div>
                    </div>
                    <div id="readerBody" class="reader-frame reader-scroll">
                        <div class="reader-loading">正在通过服务端拉取教材切片（首次打开约需 30-60 秒），请稍候...</div>
                    </div>
                </div>
            `;
            mask.addEventListener('click', (e) => { if (e.target === mask) closeReaderModal(); });
            document.body.appendChild(mask);
            document.body.style.overflow = 'hidden';

            const body = document.getElementById('readerBody');
            try {
                const res = await fetch(`/api/reader/prepare/${bookId}`);
                const data = await res.json();
                if (data.status === 'ok' && data.pages && data.pages.length > 0) {
                    body.innerHTML = data.pages.map(u => `<img src="${u}" loading="lazy" class="reader-page">`).join('');
                } else if (data.status === 'preparing') {
                    body.innerHTML = `<div class="reader-loading">${data.message}</div>`;
                } else {
                    body.innerHTML = `<div class="reader-loading">切片拉取失败：${data.message || '未知错误'}</div>`;
                }
            } catch (e) {
                body.innerHTML = `<div class="reader-loading">请求异常: ${e}</div>`;
            }
        }

        function closeReaderModal() {
            const mask = document.getElementById('readerMask');
            if (mask) mask.remove();
            document.body.style.overflow = '';
        }

        function openImagePreview(imgUrl, title) {
            if (document.getElementById('imgPreviewMask')) return;
            const mask = document.createElement('div');
            mask.id = 'imgPreviewMask';
            mask.className = 'imgpreview-mask';
            mask.innerHTML = `
                <img src="${imgUrl}" class="imgpreview-img" alt="${title}">
                <div class="imgpreview-title">${title}</div>
            `;
            const img = mask.querySelector('.imgpreview-img');
            img.style.transition = 'transform 0.12s ease';
            let scale = 1;
            mask.addEventListener('wheel', (e) => {
                e.preventDefault();
                scale = Math.min(5, Math.max(0.4, scale + (e.deltaY < 0 ? 0.15 : -0.15)));
                img.style.transform = `scale(${scale})`;
            }, { passive: false });
            mask.addEventListener('dblclick', () => {
                scale = 1;
                img.style.transform = 'scale(1)';
            });
            mask.addEventListener('click', closeImagePreview);
            document.body.appendChild(mask);
            document.body.style.overflow = 'hidden';
        }

        function closeImagePreview() {
            const mask = document.getElementById('imgPreviewMask');
            if (mask) mask.remove();
            document.body.style.overflow = '';
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const st = await res.json();
                
                document.getElementById('queueCount').innerText = st.queue_len;
                document.getElementById('spinner').style.display = st.is_running ? 'inline-block' : 'none';
                
                if (st.current_book) {
                    document.getElementById('currentTaskTitle').innerText = `正在下载: 《${st.current_book.title}》`;
                    document.getElementById('statusDetail').innerText = `${st.status_text} (${st.current_page}/${st.total_pages} 页)`;
                } else {
                    document.getElementById('currentTaskTitle').innerText = `当前状态: ${st.status_text}`;
                    document.getElementById('statusDetail').innerText = st.is_running ? '正在处理...' : '就绪';
                }
                
                document.getElementById('progressBar').style.width = `${st.progress_percent}%`;
                document.getElementById('progressPercent').innerText = `${st.progress_percent}%`;
            } catch (e) {}
        }

        window.addEventListener('resize', applyGridMaxHeight);
        window.onload = init;

        function showToast(message, type = 'info', duration = 3000) {
            const container = document.getElementById('toastContainer');
            const item = document.createElement('div');
            item.className = `toast-item ${type}`;
            item.innerHTML = `<span class="toast-dot"></span><span>${message}</span>`;
            container.appendChild(item);
            setTimeout(() => {
                item.classList.add('toast-out');
                item.addEventListener('animationend', () => item.remove());
            }, duration);
        }

        function showConfirm(message, title = '操作确认') {
            return new Promise(resolve => {
                const mask = document.createElement('div');
                mask.className = 'modal-mask';
                mask.innerHTML = `
                    <div class="modal-card">
                        <div class="modal-title">${title}</div>
                        <div class="modal-message">${message}</div>
                        <div class="modal-actions">
                            <button data-act="cancel" class="px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md transition border border-slate-200">取消</button>
                            <button data-act="ok" class="px-3 py-1.5 text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-md transition shadow-sm">确定</button>
                        </div>
                    </div>
                `;
                const close = (result) => {
                    mask.remove();
                    resolve(result);
                };
                mask.addEventListener('click', (e) => {
                    if (e.target === mask) close(false);
                    else if (e.target.dataset.act === 'ok') close(true);
                    else if (e.target.dataset.act === 'cancel') close(false);
                });
                document.body.appendChild(mask);
            });
        }
    </script>

    <!-- Toast 通知容器 -->
    <div id="toastContainer"></div>
</body>
</html>
    """
    return html_content


def main():
    import socket
    def is_port_in_use(p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', p)) == 0

    default_port = 8000 if not is_port_in_use(8000) else 8080
    port = int(os.environ.get("PORT", default_port))
    url = f"http://127.0.0.1:{port}"
    print("=" * 65)
    print("      🚀 人教社电子教材 WebUI 服务器正在启动...")
    print(f"      🔗 请在浏览器打开: {url}")
    print("=" * 65)
    
    # 自动打开默认浏览器
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
