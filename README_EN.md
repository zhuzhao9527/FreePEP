# PEP Digital Textbook Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
## <div align="center"><b><a href="README_EN.md">English</a> | <a href="README.md">简体中文</a></b></div>

An automated textbook fetching and PDF compilation tool designed for the [People's Education Press (PEP) Digital Textbook Platform](https://jc.pep.com.cn/).

It features an automated decryption engine for the full catalog of 780+ textbooks and an automatic WAF slider bypass mechanism, supporting batch downloading of textbook page images for specified educational stages, subjects, and grades, then compiling them into PDF files.

> **Derivative work notice**: This project is a fork based on [siknet/FreePEP](https://github.com/siknet/FreePEP), with a redesigned WebUI and new features such as server-relayed online reading. Credits to the original author. Neither the original project nor this one is affiliated with the People's Education Press.

## 📸 Preview

![WebUI Preview](preview.png)

## ✨ Features

### WebUI (`python webui.py`)
- **Hierarchical filters**: educational stage / subject / grade, with a collapsible filter panel
- **Keyword search**: global title search, combinable with filters
- **Cover preview**: click a cover to enlarge it, scroll wheel to zoom, double-click to reset
- **Online reading**: textbook pages are fetched through a server-side Playwright relay and browsed in-page; the first open takes about 30-60 seconds, afterwards it opens instantly from local cache
- **Batch download**: one-click batch downloading with checkboxes, real-time progress, and optional high-resolution (large) images
- **Pagination**: configurable page size (20/50/100/200), inner scrolling for large lists
- **Cache management**: clear temp page cache, sync latest catalog, quick-open download folder

### CLI (`python cli.py`)
- Interactive numeric menu navigation and direct command-line arguments, suitable for scripting and server environments

### Full archive download (`python download_all.py`)
- Multi-threaded concurrent downloading, auto-archived into a "stage / grade" two-level directory
- Smart resume: finished textbooks are skipped automatically, interrupted runs continue seamlessly
- Temp page cache is cleaned automatically after PDF compilation

---

## 🚀 Getting Started

### Method 1: Run from Source

```bash
# Clone the repository
git clone https://github.com/zhuzhao9527/FreePEP.git
cd FreePEP

# Install Python dependencies
pip install -r requirements.txt

# Install the Chromium browser kernel required by Playwright
playwright install chromium
```

#### Launch the WebUI
```bash
python webui.py
```
- URL: `http://127.0.0.1:8000`
- Default download directory: `./downloads` under the project root

#### Use the CLI
```bash
# 1. Interactive menu mode
python cli.py

# 2. Download all textbooks for Grade 1 (primary school)
python cli.py --xd "小学" --nj "一年级" -y

# 3. Download all high school mathematics textbooks
python cli.py --xd "高中" --xk "数学" -y

# 4. Global keyword search and download
python cli.py --search "物理"

# 5. Clear the local temp image cache
python cli.py --clear-cache
```

**Arguments**:

| Argument | Description | Example |
| :--- | :--- | :--- |
| `--xd` | Educational stage | `小学（六三学制）`, `初中（七-九年级）`, `高中`, `培智学校`, `聋校`, `盲校（盲文版）`, `盲校（低视力版）` |
| `--xk` | Subject | `语文`, `数学`, `英语`, `物理`, `化学`, `历史`, `道德与法治`, etc. |
| `--nj` | Grade / volume | `一年级` ... `九年级`, `专项`, `必修`, etc. |
| `--search`, `-s` | Global keyword search | `必修`, `高一`, `地理` |
| `--high-res`, `--hd` | Download high-res images (`large`), default is `mobile` | flag |
| `--clear-cache`, `-c` | Clear the local temp image cache (`temp_pages`) | flag |
| `--refresh`, `-r` | Force re-fetch and decrypt the latest catalog | flag |
| `--output`, `-o` | PDF output directory | default: `./downloads` |
| `--yes`, `-y` | Skip confirmation prompts | flag |

#### Full multi-threaded archive download
```bash
# Download the entire catalog (3 threads by default, archived by stage/grade)
python download_all.py

# Custom thread count and stage combination
python download_all.py --xd "小学（六三学制）,初中（七-九年级）,高中" -w 10 -o "D:/人教社教材"
```

### Method 2: Build a Standalone Windows EXE

```bash
python build_exe.py
```

The build script automatically:
1. Checks and installs the `PyInstaller` build tool
2. Bundles the WebUI and all dependencies into a standalone `FreePEP.exe`
3. Embeds a portable Chromium browser kernel into the `browsers/` directory
4. Generates a release archive under `dist/`; extract it and double-click `FreePEP.exe` to run

---

## 📁 Project Structure

```text
FreeNow/
├── pep_core.py          # Core library (AES decryption, Playwright scraping, PDF compilation)
├── webui.py             # FastAPI WebUI server and all-in-one frontend
├── cli.py               # Interactive and argument-driven CLI downloader
├── download_all.py      # Full-catalog downloader with staging/grade archiving and resume
├── build_exe.py         # One-click Windows EXE packaging script
├── pep_crawler.py       # CLI test and example download script
├── pep_catalog.json     # Local cache of the full textbook metadata (auto-generated)
├── requirements.txt     # Python dependency list
├── temp_pages/          # Temp image cache (online reading pages and download intermediates)
└── downloads/           # Default output directory for generated PDFs
```

---

## ❓ FAQ

### Q: Why does online reading take long on first open?
Expected behavior. The first open requires the server-side Playwright to pass WAF and fetch all page images (about 30-60 seconds). Subsequent opens hit the local cache and load instantly.

### Q: No PDF appears in `downloads` after downloading?
Background downloading relies on the headless Chromium driven by Playwright. If you only ran `pip install -r requirements.txt` and skipped the browser kernel, an `Executable doesn't exist` error occurs. Install it with:
```bash
playwright install chromium
```
> Tip: check the console output of `python webui.py` for detailed errors.

---

## ⚠️ Disclaimer

1. This project is intended for web-scraping study, reverse-engineering research, and personal learning only. Any commercial use is strictly prohibited.
2. All textbooks downloaded via this project are copyrighted by the **People's Education Press (PEP)** and relevant rights holders. This project is not affiliated with or authorized by the People's Education Press.
3. Please control request rates. Do not impose excessive load on official servers. Delete downloaded content within 24 hours; purchase official publications for long-term use.
4. This project is a derivative work based on [siknet/FreePEP](https://github.com/siknet/FreePEP) and is provided "as is" under the MIT license, **without warranty of any kind**. Neither the original author nor the maintainer of this fork shall be liable for any direct or indirect losses arising from its use.
5. Users bear full responsibility for any legal disputes arising from copyright violations or improper use, and both the original author and the maintainer of this fork are held harmless.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
