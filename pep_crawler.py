"""
人教社电子教材 (https://jc.pep.com.cn/) 完整下载与爬取工具
修复与增强特性：
1. 强制携带 Referer: https://jc.pep.com.cn/ 防盗链标头（解决直接访问返回 403 / 404.html 问题）
2. 增加图片二进制特征校验 (JPEG 0xFFD8 魔数)，杜绝误存 WAF 拦截的 HTML 页面
3. 增加中途触发 WAF 验证码时的动态拦截与自动破解重试机制
4. 修复控制台中文输出与 meta 标签教材名称提取
5. 自动批量下载并合成为标准高清 PDF 文件
"""

import os
import sys
import re
import time
import json
import random
import base64
import binascii
import urllib.request
from typing import List, Dict, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from PIL import Image
from playwright.sync_api import sync_playwright

# 保证 Windows 控制台 UTF-8 中文正常输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class PepTextbookManager:
    """负责解析与解密人教社全量教材目录数据"""
    
    BASE_URL = "https://jc.pep.com.cn/"
    KEY = b"1234123412ABCDEF"
    IV = b"ABCDEF1234123412"

    @classmethod
    def get_all_textbooks(cls) -> List[Dict]:
        """从网站前端 JS 中提取并解密全量教材列表"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": cls.BASE_URL
        }
        
        # 1. 获取首页 HTML，定位 chunk-bfbdf2c4 JS 文件
        req = urllib.request.Request(cls.BASE_URL, headers=headers)
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            
        chunk_match = re.search(r'src="(/js/chunk-bfbdf2c4\.[a-f0-9]+\.js)"', html)
        if not chunk_match:
            chunk_match = re.search(r'href="(/js/chunk-bfbdf2c4\.[a-f0-9]+\.js)"', html)
            
        chunk_path = chunk_match.group(1) if chunk_match else "/js/chunk-bfbdf2c4.3782cce3.js"
        chunk_url = urllib.parse.urljoin(cls.BASE_URL, chunk_path)
        
        # 2. 下载 JS 文件
        js_req = urllib.request.Request(chunk_url, headers=headers)
        with urllib.request.urlopen(js_req) as resp:
            js_content = resp.read().decode("utf-8", errors="ignore")
            
        # 3. 提取十六进制密文字符串
        c_match = re.search(r'var\s+o,\s*c\s*=\s*"([A-F0-9]+)"', js_content)
        if not c_match:
            raise ValueError("未能从前端 JS 中匹配到教材数据密文！")
            
        hex_ciphertext = c_match.group(1)
        cipher_bytes = binascii.unhexlify(hex_ciphertext)
        
        # 4. AES-128-CBC 解密
        cipher = Cipher(algorithms.AES(cls.KEY), modes.CBC(cls.IV))
        decryptor = cipher.decryptor()
        padded_plain = decryptor.update(cipher_bytes) + decryptor.finalize()
        
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plain) + unpadder.finalize()
        
        data_json = json.loads(plaintext.decode("utf-8", errors="ignore"))
        return data_json.get("data", [])


class PepBookDownloader:
    """基于 Playwright 的无头浏览器，负责过防盗链与 WAF 滑块验证、抓取页面并合成 PDF"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless

    def _solve_slider(self, page) -> bool:
        """自动检测并滑动通过阿里云 WAF NoCaptcha 滑块"""
        time.sleep(1)
        slider = page.query_selector(".btn_slide")
        if not slider:
            return True
            
        print("[*] 检测到阿里云 WAF 滑块验证码，正在自动滑动破解...")
        box = slider.bounding_box()
        scale = page.query_selector(".nc_scale")
        scale_box = scale.bounding_box() if scale else None
        
        if not (box and scale_box):
            print("[-] 未能获取滑块坐标")
            return False
            
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        target_x = scale_box["x"] + scale_box["width"] + 20
        
        # 模拟人类拖动轨迹
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        
        curr_x = start_x
        while curr_x < target_x:
            curr_x += random.randint(12, 28)
            curr_y = start_y + random.randint(-2, 2)
            page.mouse.move(curr_x, curr_y)
            time.sleep(random.uniform(0.01, 0.025))
            
        page.mouse.move(target_x, start_y)
        page.mouse.up()
        time.sleep(3)
        
        if page.query_selector(".btn_slide"):
            print("[-] 滑块验证未通过，尝试二次滑动...")
            return False
        print("[+] 滑块验证通过！已成功获取访问权限。")
        return True

    def download_book(self, book_id: str, output_pdf: Optional[str] = None) -> Optional[str]:
        """下载指定 ID 的电子教材并转换为 PDF"""
        book_url = f"https://book.pep.com.cn/{book_id}/"
        print(f"[*] 开始准备下载教材: {book_url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={
                    "Referer": "https://jc.pep.com.cn/"
                }
            )
            # 抹除 WebDriver 特征以规避反爬
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
            """)
            page = context.new_page()
            
            # 打开教材阅读页面（必须附带 Referer 防 403 拦截）
            page.goto(book_url, referer="https://jc.pep.com.cn/", wait_until="networkidle")
            
            # 处理可能的滑块验证
            if page.query_selector(".btn_slide"):
                self._solve_slider(page)
                time.sleep(3)
                
            # 等待阅读器页面及配置加载
            for _ in range(15):
                has_config = page.evaluate("""() => {
                    return typeof window.bookConfig !== 'undefined' || 
                           typeof window.totalPageCount !== 'undefined' ||
                           document.querySelector('#bookContainer') !== null;
                }""")
                if has_config:
                    break
                time.sleep(1)
            
            # 获取教材配置与总页数
            config_info = page.evaluate("""() => {
                const descMeta = document.querySelector('meta[name="Description"]');
                const ogMeta = document.querySelector('meta[property="og:title"]');
                const title = (descMeta ? descMeta.content : '') || 
                              (ogMeta ? ogMeta.content : '') || 
                              (window.bookConfig && window.bookConfig.bookTitle) || 
                              document.title || 
                              '教材';
                const total = window.totalPageCount || 
                              (window.bookConfig && window.bookConfig.totalPageCount) || 
                              0;
                return { title, total };
            }""")
            
            raw_title = config_info.get("title", f"book_{book_id}")
            book_title = re.sub(r'[\/:*?"<>|]', '_', raw_title).strip()
            total_pages = config_info.get("total", 0)
            
            if total_pages == 0:
                print("[-] 未能获取教材总页数，可能页面被重定向或未完全加载！")
                print(f"    当前页面 URL: {page.url}")
                print(f"    当前页面 Title: {page.title()}")
                browser.close()
                return None
                
            print(f"[+] 教材名称: 《{book_title}》 | 总页数: {total_pages} 页")
            
            # 准备临时图片保存目录
            temp_dir = os.path.join(".", "temp_pages", book_id)
            os.makedirs(temp_dir, exist_ok=True)
            
            image_files = []
            
            # 遍历下载每一页高清图片
            for page_num in range(1, total_pages + 1):
                img_url = f"https://book.pep.com.cn/{book_id}/files/mobile/{page_num}.jpg"
                img_path = os.path.join(temp_dir, f"{page_num}.jpg")
                
                # 检查本地已有文件是否为有效 JPEG
                if os.path.exists(img_path) and os.path.getsize(img_path) > 15000:
                    with open(img_path, "rb") as f:
                        header = f.read(2)
                    if header == b"\xff\xd8":
                        image_files.append(img_path)
                        continue
                
                # 在浏览器会话内下载
                download_success = False
                for retry in range(3):
                    res = page.evaluate("""async (url) => {
                        try {
                            const resp = await fetch(url);
                            const ctype = resp.headers.get('content-type') || '';
                            const blob = await resp.blob();
                            return new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve({ 
                                    status: resp.status, 
                                    ctype: ctype, 
                                    data: reader.result 
                                });
                                reader.readAsDataURL(blob);
                            });
                        } catch (e) {
                            return { status: 500, error: e.toString() };
                        }
                    }""", img_url)
                    
                    data_uri = res.get("data", "")
                    if res.get("status") == 200 and data_uri and ("image" in res.get("ctype", "") or data_uri.startswith("data:image")):
                        raw_data = base64.b64decode(data_uri.split(",")[1])
                        # 校验 JPEG 魔数 0xFF 0xD8
                        if raw_data[:2] == b"\xff\xd8":
                            with open(img_path, "wb") as f:
                                f.write(raw_data)
                            image_files.append(img_path)
                            print(f"  -> [{page_num}/{total_pages}] 下载成功 ({len(raw_data) // 1024} KB)")
                            download_success = True
                            break
                    
                    # 如果返回的是 HTML 页面，说明触发了 WAF 验证码拦截
                    print(f"  [!] 第 {page_num} 页触发 WAF 验证，尝试刷新并过验证...")
                    page.goto(book_url, referer="https://jc.pep.com.cn/", wait_until="networkidle")
                    self._solve_slider(page)
                    time.sleep(2)
                    
                if not download_success:
                    print(f"  -> [{page_num}/{total_pages}] 下载失败！")
                    
                time.sleep(random.uniform(0.15, 0.35))
                
            browser.close()
            
            # 校验并合成 PDF
            if not image_files:
                print("[-] 未下载到任何有效图片！")
                return None
                
            if not output_pdf:
                output_pdf = f"{book_title}.pdf"
                
            print(f"[*] 正在将 {len(image_files)} 页图片合并为 PDF: {output_pdf} ...")
            
            pil_images = []
            for img_p in image_files:
                try:
                    im = Image.open(img_p)
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    pil_images.append(im)
                except Exception as e:
                    print(f"[-] 图片损坏跳过: {img_p}, 错误: {e}")
                    
            if not pil_images:
                print("[-] 无有效图片可供合成！")
                return None
                
            first_im = pil_images[0]
            rest_images = pil_images[1:]
            first_im.save(output_pdf, "PDF", resolution=100.0, save_all=True, append_images=rest_images)
            
            print(f"[✔] 下载并生成 PDF 成功: {os.path.abspath(output_pdf)}")
            return output_pdf


if __name__ == "__main__":
    print("=" * 60)
    print("1. 正在获取并解密人教社全量教材目录...")
    textbooks = PepTextbookManager.get_all_textbooks()
    print(f"[+] 成功解析出 {len(textbooks)} 本教材！")
    
    # 保存全部目录到本地 json
    with open("pep_catalog.json", "w", encoding="utf-8") as f:
        json.dump(textbooks, f, ensure_ascii=False, indent=2)
    print("[+] 全量教材目录已保存至: pep_catalog.json")
    
    print("\n" + "=" * 60)
    print("2. 演示下载一本教材（以 ID: 1284001101241 为例）...")
    downloader = PepBookDownloader(headless=True)
    downloader.download_book("1284001101241")
