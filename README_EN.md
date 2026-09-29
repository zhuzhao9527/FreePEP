# FreePEP 📚 PEP Primary & Secondary School Digital Textbook Batch Downloader
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**FreePEP** is an automated textbook parsing, batch downloading, and high-definition PDF compilation tool specifically designed for the [People's Education Press (PEP) Digital Textbook Platform](https://jc.pep.com.cn/).

It offers both a **modern WebUI interface** and an **interactive command-line interface (CLI)**. Featuring an automated decryption engine for over 780+ complete textbooks (data as of August 31, 2026) and a bypass mechanism for Alibaba Cloud WAF slider captchas, FreePEP enables one-click downloading of entire sets of textbooks across specified educational stages, subjects, and grades, compiling them directly into high-res PDF files.

---

# 📦 Packaged Textbook Download Area (Updated: September 11, 2026)

> *Friendly reminder: This is public educational data. Please avoid downloading the entire catalog at once. Downloading over several days helps ease server load for everyone.*
> *We have migrated to a Cloudflare D1 database backend for better stability.*
> 
> **If this project helps you, please consider giving it a ⭐ Star!**

- **Primary School (6-3 System)**: [Plain Text List](txtlist.md) | [Visual List](piclist.md)
- **Junior High School (Grades 7–9)**: [Plain Text List](789txtlist.md) | [Visual List](789piclist.md)
- **Senior High School**: [Plain Text List](gztxtlist.md) | [Visual List](gzpiclist.md)

---

## ✨ Key Features

- 🎯 **Dual Operation Modes**:
  - **Modern WebUI Interface**: Fully responsive layout matching the official website's category hierarchy. Features one-click batch checkbox downloads, real-time progress bars, and a quick-open button for the download folder.
  - **Interactive CLI Terminal**: Offers intuitive numeric menu navigation or direct command-line arguments (ideal for automation scripts and headless server environments).
- 📦 **High-Resolution Page Fetching & PDF Compilation**: Automatically detects the exact page count of each textbook, downloads the original high-resolution JPG pages in batch, and compiles them into standard PDF files using Pillow.

---

## 📸 Screenshots

### WebUI
![](https://img.wemd.app/1788139668274_4n5d28.png)

---

### CLI Terminal
![](https://img.wemd.app/1788139734008_2tmuak.png)

---

# 🚀 Getting Started

## 🖥️ Method 1: Portable Release (Recommended for Beginners)
Simply download the prebuilt release package, extract the archive, and run `FreePEP.exe`. It will automatically launch the WebUI in your default browser for easy downloading.

## Method 2: Running from Source

### Clone the Repository and Install Dependencies
```bash
# Clone the repository
git clone https://github.com/siknet/FreePEP.git
cd FreePEP

# Install Python dependencies
pip install -r requirements.txt

# Install the Chromium browser engine required by Playwright
playwright install chromium
```

### Launch Option 1: WebUI
Run the following command in your terminal. The server will start locally and automatically open the management page in your default browser:
```bash
python webui.py
```
* **WebUI Address**: `http://127.0.0.1:8000`
* **Default Download Folder**: `./downloads` in the project root (you can also click "📁 Open Save Folder" on the WebUI).

---

### Launch Option 2: CLI (Command-Line Interface)
#### 1. Interactive Menu Mode
Run `cli.py` directly and follow the interactive console prompts to select educational stage, subject, and grade:
```bash
python cli.py
```

#### 2. Argument-Driven Mode (Ideal for automation and scripts)
Filter and download directly via command-line arguments:

```bash
# 1. Download all textbooks for Primary School Grade 1
python cli.py --xd "小学" --nj "一年级" -y

# 2. Download all compulsory & elective textbooks for High School Mathematics
python cli.py --xd "高中" --xk "数学" -y

# 3. Download all Junior High School textbooks
python cli.py --xd "初中" -y

# 4. Search and download by keyword (e.g., all textbooks containing "物理" / Physics)
python cli.py --search "物理"

# 5. Clean temporary image cache
python cli.py --clear-cache

# 6. Specify custom PDF output directory
python cli.py --xd "小学（六三学制）" --xk "语文" --nj "一年级" -o "D:/Textbooks" -y
```

**CLI Argument Reference**:
| Argument | Description | Example |
| :--- | :--- | :--- |
| `--xd` | Educational stage | `小学（六三学制）`, `初中（六三学制）`, `小学（五四学制）`, `初中（五·四学制）`, `高中`, `培智学校`, `聋校`, `盲校（盲文版）`, `盲校（低视力版）` |
| `--xk` | Subject | `语文` (Chinese), `数学` (Math), `英语` (English), `物理` (Physics), `化学` (Chemistry), `历史` (History), `道德与法治` (Ethics), etc. |
| `--nj` | Grade / Volume | `一年级` (Grade 1), `二年级` ... `九年级` (Grade 9), `专项` (Special), `必修` (Compulsory), etc. |
| `--search`, `-s` | Global keyword search | `必修`, `高一`, `地理` |
| `--clear-cache`, `-c`| Remove local temporary image cache (`temp_pages`) | No argument needed |
| `--refresh`, `-r` | Force refetch & decrypt the latest catalog from server | No argument needed |
| `--output`, `-o` | Specify PDF output directory | Default: `./downloads` |
| `--yes`, `-y` | Skip confirmation prompts and download immediately | Flag |

---

### Launch Option 3: Hierarchical Multi-Threaded Batch Downloader (`download_all.py`)

To archive and organize textbooks into a clean two-level hierarchy (`Educational_Stage/Grade/`), use the dedicated high-speed multi-threaded downloader:

```bash
# 1. Download the entire catalog (Default: 3 threads, auto-sorted into Stage/Grade subdirectories)
python download_all.py

# 2. Increase concurrent threads (e.g., 10 parallel threads for high-speed downloading)
python download_all.py -w 10

# 3. Download multiple stages (comma-separated: 6-3, 5-4, and High School) to a custom directory
python download_all.py --xd "义务教育（六三学制）,义务教育（五四学制）,高中" -w 10 -o "D:/PEP_Textbooks"

# 4. Download only a single stage (e.g., all High School textbooks)
python download_all.py --xd "高中"

# 5. Download only a specific grade
python download_all.py --nj "一年级"
```

**Features**:
* 🚀 **Multi-Threaded Acceleration**: Defaults to **3 threads**, customizable via `-w / --workers` (e.g., 5–10 threads) for significantly faster downloads.
* 🎯 **Multiple Stage Filtering**: `--xd` accepts multiple comma-separated stages, allowing focused downloads of general education materials while skipping special education books.
* 🌲 **Structured Hierarchy**: Automatically saves files as `downloads/<Stage>/<Grade>/<Book_Name>.pdf`, preventing hundreds of files from cluttering a single folder.
* ⚡ **Smart Resume & Skip**: Already completed textbooks are **instantly skipped**, allowing seamless resumes if interrupted without redundant downloads.
* 🧹 **Automatic Cleanup**: Temporary page slices are purged right after the PDF is assembled, saving disk space.
* 💬 **Clean Output**: Suppresses verbose per-page logs; prints clean status updates only when a textbook finishes or is skipped.

---

## 📦 Build a Standalone Windows EXE

To package this project into an independent, portable package that **runs without Python installed**:

```bash
python build_exe.py
```

### The build script automatically handles:
1. Checking and installing the `PyInstaller` tool.
2. Compiling the WebUI and all Python dependencies into `FreePEP.exe`.
3. **Extracting and embedding a portable Chromium browser engine** into the `browsers/` directory.
4. Generating a ready-to-distribute `FreePEP-Windows-x64.zip` in the `dist/` directory.

> **End-User Distribution**: Users simply extract the ZIP and **double-click `FreePEP.exe`** (it automatically opens the WebUI in their default browser—no Python, no environment variables, and no browser downloads required).

---

## 📁 Project Structure

```text
FreePEP/
├── pep_core.py          # Core engine (AES decryption, Playwright scraping, PDF compilation)
├── webui.py             # FastAPI WebUI server & integrated frontend
├── cli.py               # Interactive & argument-driven CLI downloader
├── download_all.py      # Hierarchical batch downloader (Stage/Grade organization, resume support)
├── build_exe.py         # One-click script for building the standalone Windows portable package
├── pep_crawler.py       # CLI testing and demonstration script
├── pep_catalog.json     # Local cached textbook metadata (auto-generated)
├── requirements.txt     # Python dependencies
├── README.md            # Project documentation (English)
├── temp_pages/          # Temporary page download cache (cleaned up automatically)
└── downloads/           # Default output directory for generated PDFs
```

---

## 🔍 Technical Implementation Notes

1. *(Omitted - Personal opinion: It remains unclear why digital textbooks made freely accessible for online reading cannot be officially provided with direct download options.)*

---

## ⚠️ Disclaimer

1. This project is intended solely for technical exchange regarding Python web scraping, reverse engineering learning, and personal educational research. Any commercial or profitable use is strictly prohibited.
2. All copyrights of the downloaded textbooks belong to **People's Education Press (PEP)** and their respective copyright holders.
3. Please throttle request rates responsibly when using this tool. Actions that place excessive load on the official servers are strictly prohibited. Please delete downloaded materials within 24 hours of use. For long-term use, please purchase or support official genuine publications.
4. Any legal disputes or liabilities arising from copyright violations or improper use shall be borne entirely by the user; the author of this project assumes no responsibility.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE). Contributions, issues, and pull requests are welcome!
