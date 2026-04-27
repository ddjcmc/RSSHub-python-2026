import sqlite3
import threading
import os
import time
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, urlunparse
import requests
import datetime
from rsshub.utils import DEFAULT_HEADERS, fetch  # 保持原有导入

# ==================== 常量与配置 ====================
domain_url = "https://everia.club"

# 数据库放在当前脚本同目录
DB_PATH = os.path.join(os.path.dirname(__file__), "everia_cache.db")

# ==================== 数据库初始化 ====================
def get_db():
    """获取数据库连接（每个线程独立连接）"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """创建表结构：以 standardized_link 为主键，original_link 保留原始网址"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            standardized_link TEXT PRIMARY KEY,
            original_link TEXT NOT NULL,
            title TEXT,
            author TEXT,
            pubDate TEXT,
            description TEXT,
            category TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# 模块加载时自动初始化
init_db()

# ==================== 后台任务控制 ====================
_running_tasks = {}
_lock = threading.Lock()

def start_background_task(category: str):
    """如果该分类没有正在运行的任务，则启动一个新线程执行更新"""
    with _lock:
        if category in _running_tasks and _running_tasks[category].is_alive():
            return
        t = threading.Thread(target=_update_category, args=(category,), daemon=True)
        _running_tasks[category] = t
        t.start()

def _update_category(category: str):
    """
    后台爬虫与缓存更新：
    1. 获取分类首页前7篇文章
    2. 对每一篇，检查数据库是否已有缓存（根据标准化后的链接）
       - 有：直接使用数据库中的记录
       - 无：爬取完整内容并生成记录
    3. 用这10篇数据替换数据库中该分类的全部记录
    """
    try:
        url = url_builder(category)
        print(f"[后台] 开始更新分类: {category}")
        res = requests.get(url, headers=DEFAULT_HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        posts = soup.find('div', id='blog-entries').find_all(id=re.compile(r'^post-'))
        posts = posts[:7]
        print(f"[后台] 找到 {len(posts)} 篇文章")

        # 收集最终要插入的条目
        final_items = []
        conn = get_db()
        try:
            for post in posts:
                title_tag = post.select_one('.blog-entry-title a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                original_link = title_tag.get('href')
                std_link = normalize_url(original_link)

                # 检查数据库是否已有该文章（按标准化链接）
                cur = conn.execute(
                    "SELECT title, author, pubDate, description FROM items WHERE standardized_link = ?",
                    (std_link,)
                )
                cached = cur.fetchone()

                if cached:
                    # 已有缓存，直接复用（不重复爬取）
                    print(f"[后台] 跳过已缓存: {title}")
                    final_items.append({
                        'standardized_link': std_link,
                        'original_link': original_link,
                        'title': cached['title'],
                        'author': cached['author'],
                        'pubDate': cached['pubDate'],
                        'description': cached['description'],
                        'category': category
                    })
                else:
                    # 首次抓取，获取完整描述
                    print(f"[后台] 抓取新文章: {title}")
                    description = fetch_content(original_link)
                    final_items.append({
                        'standardized_link': std_link,
                        'original_link': original_link,
                        'title': title,
                        'author': 'unknown',
                        'pubDate': datetime.datetime.now().time().isoformat(),
                        'description': description,
                        'category': category
                    })

            # 事务：替换该分类下的所有记录
            with conn:
                conn.execute("DELETE FROM items WHERE category = ?", (category,))
                conn.executemany(
                    """INSERT INTO items 
                       (standardized_link, original_link, title, author, pubDate, description, category)
                       VALUES (:standardized_link, :original_link, :title, :author, :pubDate, :description, :category)""",
                    final_items
                )
            print(f"[后台] {category} 更新完成，写入 {len(final_items)} 条记录")
        finally:
            conn.close()
    except Exception as e:
        print(f"[后台] 更新 {category} 时出错: {e}")

# ==================== 从数据库加载缓存 ====================
def load_items_from_db(category: str):
    """读取指定分类的所有条目，返回原 RSS 所需格式"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT title, original_link, author, pubDate, description FROM items WHERE category = ?",
            (category,)
        ).fetchall()
        items = []
        for row in rows:
            items.append({
                'title': row['title'],
                'link': row['original_link'],      # 返回原始链接给 RSS 用户
                'author': row['author'],
                'pubDate': row['pubDate'],
                'description': row['description']
            })
        return items
    finally:
        conn.close()

# ==================== 辅助函数（保持不变） ====================
def url_builder(category: str = "chinese"):
    return domain_url + f"/category/{category}/"

def fetch_content(start_url):
    need_url = [start_url] + [f"{start_url}{i}" for i in range(2, 7)]
    article_full = ""
    for url in need_url:
        resp = requests.get(url, allow_redirects=True)
        print(resp.url)
        if normalize_url(resp.url) != normalize_url(url):
            print(f"最终地址: {resp.url}")
            break
        soup = BeautifulSoup(resp.text, 'html.parser')
        content_div = soup.find(id='content')
        if content_div:
            img_tags = content_div.find_all('img')
            article_full += ''.join(str(img) for img in img_tags)
    return article_full

def normalize_url(url: str) -> str:
    """规范化网址用于比较/存储"""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    params = parsed.params.lower()
    query = parsed.query.lower()
    fragment = parsed.fragment.lower()
    normalized = urlunparse((scheme, netloc, path, params, query, fragment))
    if normalized.endswith('/') and len(normalized) > 1:
        normalized = normalized.rstrip('/')
    return normalized

# ==================== 对外接口 ctx ====================
def ctx(category: str = "chinese"):
    """
    响应用户 RSS 请求：
    - 立即从数据库返回当前分类的缓存（最新10篇文章）
    - 同时触发后台更新（不会阻塞响应）
    """
    # 1. 加载缓存
    items = load_items_from_db(category)
    
    # 2. 启动后台更新（如果当前无任务则开始爬虫）
    start_background_task(category)
    
    # 3. 返回 RSS 结构
    return {
        'title': f'everia {category}',
        'link': url_builder(category),
        'description': f'everia - {category}',
        'author': 'unknown',
        'items': items
    }
