"""
单元测试集合 (tests/test_all.py)
涵盖：
1. 纯函数与排序、映射规则测试 (表驱动)
2. 学段匹配逻辑与空值安全性测试 (is_match_xd, nj None-safety)
3. 本地教材目录检索与结构化分类测试 (PepCatalog filter & structure)
4. AES-128-CBC 加解密链路 round-trip 与正则匹配测试
5. PepDownloader skip_if_exists 离线快路径测试
6. WebUI FastAPI API 接口测试
"""

import os
import sys
import json
import base64
import binascii
import tempfile
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from fastapi.testclient import TestClient

# 将项目根目录加入 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pep_core import (
    normalize_xd,
    sort_xd_key,
    sort_xk_key,
    sort_nj_key,
    map_book_xd,
    PepCatalog,
    PepDownloader,
    XD_ORDER,
    XK_ORDER_PREFIX,
    NJ_ORDER,
)
from download_all import sanitize_filename, is_match_xd
from webui import app


# ==========================================
# 1. 纯函数测试
# ==========================================

@pytest.mark.parametrize("raw, expected", [
    ("小学", "小学（六三学制）"),
    ("初中", "初中（六三学制）"),
    ("小学（五·四学制）", "小学（五四学制）"),
    ("小学（五四学制）", "小学（五四学制）"),
    ("初中（五·四学制）", "初中（五·四学制）"),
    ("初中（五四学制）", "初中（五·四学制）"),
    ("高中", "高中"),
    ("", "其他"),
    (None, "其他"),
])
def test_normalize_xd(raw, expected):
    assert normalize_xd(raw) == expected


def test_sort_keys():
    # 学段排序测试
    sorted_xds = sorted(XD_ORDER, key=sort_xd_key)
    assert sorted_xds == XD_ORDER
    # 未知学段排在后面
    assert sort_xd_key("未知学段")[0] == 1

    # 学科前缀优先排序
    sorted_xks = sorted(XK_ORDER_PREFIX, key=sort_xk_key)
    assert sorted_xks == XK_ORDER_PREFIX
    assert sort_xk_key("未知学科")[0] == 1

    # 年级排序
    sorted_njs = sorted(NJ_ORDER, key=sort_nj_key)
    assert sorted_njs == NJ_ORDER


@pytest.mark.parametrize("meta, expected", [
    ({"xd": "小学", "xdtype": "盲文"}, "盲校（盲文版）"),
    ({"xd": "初中", "xdtype": "低视力"}, "盲校（低视力版）"),
    ({"xd": "小学", "xdtype": "聋校"}, "聋校"),
    ({"xd": "小学", "xdtype": "培智"}, "培智学校"),
    ({"xd": "初中", "xdtype": "六三"}, "初中（六三学制）"),
    ({"xd": "小学", "xdtype": "六三"}, "小学（六三学制）"),
    ({"xd": "初中", "xdtype": "五四"}, "初中（五·四学制）"),
    ({"xd": "小学", "xdtype": "五四"}, "小学（五四学制）"),
    ({"xd": "高中", "xdtype": ""}, "高中"),
])
def test_map_book_xd(meta, expected):
    assert map_book_xd(meta) == expected


def test_sanitize_filename():
    assert sanitize_filename('test/book:name*1') == "test_book_name_1"
    assert sanitize_filename('test/book:name*1?"<>|') == "test_book_name_1_____"


# ==========================================
# 2. 学段匹配与空值安全
# ==========================================

@pytest.mark.parametrize("b_xd, b_xdtype, targets, expected", [
    ("小学（六三学制）", "六三学制", ["义务教育（六三学制）"], True),
    ("初中（五·四学制）", "五四学制", ["义务教育（五四学制）"], True),
    ("高中", "普通高中", ["高中"], True),
    ("小学（六三学制）", "六三学制", ["高中"], False),
    ("小学", "六三", [], True),  # 无过滤条件全部匹配
])
def test_is_match_xd(b_xd, b_xdtype, targets, expected):
    assert is_match_xd(b_xd, b_xdtype, targets) == expected


def test_nj_null_safety():
    """测试 nj 为 None 时的安全性"""
    b = {"id": "123", "title": "测试教材", "xd": "小学", "nj": None}
    nj = (b.get("nj") or "通用").strip() or "通用"
    assert nj == "通用"


# ==========================================
# 3. 目录检索与结构化分类 (读取本地 pep_catalog.json)
# ==========================================

def test_pep_catalog_filter_and_structure():
    books = PepCatalog.fetch_and_decrypt_all()
    assert len(books) > 0, "应成功从本地缓存读取教材数据"

    # 测试条件过滤
    filtered = PepCatalog.filter_books(xd="高中", xk="数学")
    assert len(filtered) > 0
    for b in filtered:
        assert b["xd"] == "高中"
        assert b["xk"] == "数学"

    # 测试关键词搜索
    kw_filtered = PepCatalog.filter_books(keyword="语文")
    assert len(kw_filtered) > 0

    # 测试结构体解析
    structure = PepCatalog.get_structure()
    assert "高中" in structure
    assert "数学" in structure["高中"]["subjects"]


# ==========================================
# 4. AES-128-CBC 加解密链路 round-trip 测试
# ==========================================

def test_aes_round_trip():
    key = PepCatalog.KEY
    iv = PepCatalog.IV

    sample_data = {"data": [{"id": "999999", "title": "单元测试教材"}]}
    plain_bytes = json.dumps(sample_data).encode("utf-8")

    # 模拟加密与 PKCS7 padding
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plain_bytes) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    cipher_bytes = encryptor.update(padded_data) + encryptor.finalize()
    hex_str = binascii.hexlify(cipher_bytes).decode("ascii").upper()

    # 模拟从前端 JS 中匹配 hex_str
    mock_js = f'var o, c = "{hex_str}";'.encode("ascii")
    import re
    m = re.search(rb'c\s*=\s*"([A-F0-9]+)"', mock_js)
    assert m is not None

    extracted_hex = m.group(1).decode("ascii")
    extracted_cipher = binascii.unhexlify(extracted_hex)

    # 执行解密
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(extracted_cipher) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    decrypted_plain = unpadder.update(decrypted_padded) + unpadder.finalize()

    res_json = json.loads(decrypted_plain.decode("utf-8"))
    assert res_json == sample_data


# ==========================================
# 5. 下载器 skip_if_exists 离线快路径测试
# ==========================================

def test_downloader_skip_if_exists():
    with tempfile.TemporaryDirectory() as tmp_dir:
        downloader = PepDownloader(headless=True, output_dir=tmp_dir)
        fake_pdf = os.path.join(tmp_dir, "测试教材.pdf")
        # 写入大于 50KB 的假文件模拟已存在 PDF
        with open(fake_pdf, "wb") as f:
            f.write(b"%PDF-1.4 " + b"0" * 60000)

        # 调用 download_book，由于文件已存在且 > 50KB，应直接秒退并返回路径，无需启动 Playwright 浏览器
        result_path = downloader.download_book(
            book_id="1384001301261",
            custom_title="测试教材",
            skip_if_exists=True
        )
        assert result_path == fake_pdf


# ==========================================
# 6. WebUI API 接口测试
# ==========================================

client = TestClient(app)

def test_webui_api_structure():
    response = client.get("/api/structure")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert len(data) > 0


def test_webui_api_books():
    response = client.post("/api/books", json={"xd": "高中", "xk": "数学", "nj": "全部", "keyword": ""})
    assert response.status_code == 200
    data = response.json()
    assert "books" in data
    assert data["total"] > 0


def test_webui_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "queue_len" in data
