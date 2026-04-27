import sqlite3
import threading
import os
from bs4 import BeautifulSoup
import re
import requests
import datetime
from urllib.parse import urlparse, urlunparse
from rsshub.utils import DEFAULT_HEADERS, fetch  # fetch 未实际使用，保留以兼容原有导入

# ==================== 常量与配置 ====================
domain_url = "https://cosplaytele.com"


# 数据库文件放在与当前脚本相同的目录
DB_PATH = os.path.join(os.path.dirname(__file__), "cosplaytele_cache.db")

# ==================== URL 标准化 ====================
def normalize_url(url: str) -> str:
    """
    规范化 URL 用于比较和存储：
    - 转为小写
    - 去掉末尾斜杠（根目录除外）
    """
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

# ==================== 数据库初始化 ====================
def get_db():
    """获取线程安全的数据库连接"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """创建缓存表，以标准化链接作为主键"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            standardized_link TEXT PRIMARY KEY,
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

init_db()  # 模块加载时自动建表

# ==================== 后台更新线程控制 ====================
_running_tasks = {}
_lock = threading.Lock()

def start_background_task(category: str):
    """为指定分类启动后台更新（若无正在运行的任务）"""
    with _lock:
        if category in _running_tasks and _running_tasks[category].is_alive():
            return
        t = threading.Thread(target=_update_category, args=(category,), daemon=True)
        _running_tasks[category] = t
        t.start()

def _update_category(category: str):
    """
    后台核心逻辑：
    1. 访问分类首页，提取前12篇文章的标题和标准化链接
    2. 对每篇新文章（数据库无缓存）请求详情页，提取图片集合构成描述
    3. 用这12篇文章替换数据库中该分类的全部记录
    """
    try:
        url = url_builder(category)
        print(f"[后台] 开始更新分类: {category}，请求 {url}")
        res = requests.get(url, headers=DEFAULT_HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        post_items = soup.find(id="post-list").find_all("div", class_="col post-item")
        post_items = post_items[:12]  # 只取前12篇
        print(f"[后台] 找到 {len(post_items)} 篇文章")

        final_items = []
        conn = get_db()
        try:
            for post in post_items:
                a_tag = post.find("a")
                if not a_tag:
                    continue
                raw_link = a_tag.get('href')
                std_link = normalize_url(raw_link)
                title = a_tag.get('aria-label', '').strip()

                # 检查是否已有缓存
                cur = conn.execute(
                    "SELECT title, author, pubDate, description FROM items WHERE standardized_link = ?",
                    (std_link,)
                )
                cached = cur.fetchone()

                if cached:
                    # 已有缓存，直接复用
                    print(f"[后台] 跳过已缓存: {title}")
                    final_items.append({
                        'standardized_link': std_link,
                        'title': cached['title'],
                        'author': cached['author'],
                        'pubDate': cached['pubDate'],
                        'description': cached['description'],
                        'category': category
                    })
                else:
                    # 新文章：爬取详情页，提取图片
                    print(f"[后台] 抓取新文章: {title}")
                    description = ""
                    try:
                        detail_res = requests.get(std_link, headers=DEFAULT_HEADERS)
                        detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                        gallery = detail_soup.find(id="gallery-1")
                        if gallery:
                            figures = gallery.find_all("figure")
                            img_tags = []
                            for fig in figures:
                                img_a = fig.find("a")
                                if img_a and img_a.get("href"):
                                    img_tags.append(f'<img src="{img_a["href"]}" />')
                            description = "<div>\n" + "\n".join(img_tags) + "\n</div>"
                    except Exception as e:
                        print(f"[后台] 抓取文章详情失败: {std_link}，错误: {e}")
                        description = "<div></div>"  # 占位描述
                    
                    final_items.append({
                        'standardized_link': std_link,
                        'title': title,
                        'author': 'unknown',
                        'pubDate': datetime.datetime.now().time().isoformat(),
                        'description': description,
                        'category': category
                    })

            # 事务：原子替换该分类下的所有记录
            with conn:
                conn.execute("DELETE FROM items WHERE category = ?", (category,))
                conn.executemany(
                    """INSERT INTO items 
                       (standardized_link, title, author, pubDate, description, category)
                       VALUES (:standardized_link, :title, :author, :pubDate, :description, :category)""",
                    final_items
                )
            print(f"[后台] {category} 更新完成，写入 {len(final_items)} 条记录")
        finally:
            conn.close()
    except Exception as e:
        print(f"[后台] 更新 {category} 时出错: {e}")

# ==================== 数据库读取 ====================
def load_items_from_db(category: str):
    """从数据库读取指定分类的所有条目，转换为 RSS 需要的格式"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT standardized_link, title, author, pubDate, description FROM items WHERE category = ?",
            (category,)
        ).fetchall()
        items = []
        for row in rows:
            items.append({
                'title': row['title'],
                'link': row['standardized_link'],   # 返回标准化后的链接（与原 parse 行为一致）
                'author': row['author'],
                'pubDate': row['pubDate'],
                'description': row['description']
            })
        return items
    finally:
        conn.close()

# ==================== 辅助函数 ====================
def url_builder(category: str = "cosplay"):
    """构建分类页面 URL"""
    return domain_url + f"/category/{category}/"

# ==================== 对外接口 ctx ====================
def ctx(category: str = "cosplay"):
    """
    处理 RSS 请求：
    - 立即从数据库返回缓存数据（该分类下的前12篇）
    - 触发后台更新（如果当前没有正在进行的任务）
    """
    items = load_items_from_db(category)
    start_background_task(category)

    return {
        'title': f'cosplaytele {category}',
        'link': url_builder(category),
        'description': f'cosplaytele - {category}',
        'author': 'unknown',
        'items': items
    }
