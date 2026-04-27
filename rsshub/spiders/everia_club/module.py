from parsel import Selector
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, urlunparse
import requests
import datetime
from rsshub.utils import DEFAULT_HEADERS,fetch

domain_url = "https://everia.club"


# get every post
def parse(post:Selector):
    item = {}
    title_tag = post.select_one('.blog-entry-title a')
    if title_tag:
        item['title'] = title_tag.get_text(strip=True)   # 获取标题文本
        item['link'] = title_tag.get('href')             # 获取链接地址
        
    print(item['title'], item['link'])

    
    item['author'] = 'unknown'
    item['pubDate'] = datetime.datetime.now().time() # 这里需要根据实际情况解析发布时间
    
    
    item['description'] = fetch_content(item['link'])
    print(item['description']  )

    return item
    
# get content index ,num not bigger 8
def ctx(category:str="chinese"):

    url = url_builder(category)
    print(f"fetching {url} ...")
    res = requests.get(url, headers=DEFAULT_HEADERS)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    
    posts = soup.find('div', id='blog-entries').find_all(id=re.compile(r'^post-'))
   
    print(f"total {len(posts)} posts found.")


    # posts = posts_ if len(posts_) < 1 else posts_[:1]
    posts = posts[:5]
    return  {
        'title': f'everia {category}',
        'link': url,
        'description': f'everia - {category}',
        'author': 'unknown',
        'items': list(map(parse, posts)) 
    }


# get rss url
def url_builder(category:str="chinese"):
    return domain_url+f"/category/{category}/"

# 获取完整的文章内容
def fetch_content(start_url):
    need_url = [start_url] + [f"{start_url}{i}" for i in range(2, 7)]
    
    article_full = ""
    for url in need_url :  # 最多尝试6次
        #如果requests.get 发生了重定向,说明页数已经超过了最大页数,返回None
        
        #如果requests.get 发生了重定向,说明页数已经超过了最大页数,返回None
        resp = requests.get(url, allow_redirects=True)
        print(resp.url)
        if  normalize_url(resp.url)!=normalize_url(url):   # 发生任何重定向
            print(f"最终地址: {resp.url}")
            break
        soup = BeautifulSoup(resp.text, 'html.parser')
        img_tags = soup.find(id='content').find_all('img')
        article_full += ''.join(str(img) for img in img_tags)

    return article_full


def normalize_url(url: str) -> str:
    """
    规范化 URL 用于比较：
    - 转为小写
    - 去掉末尾斜杠
    - 保留 scheme、netloc、path、params、query、fragment
    （如需忽略 fragment 可自行裁剪）
    """
    # 解析 URL
    parsed = urlparse(url)
    # 将各个组件转为小写
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # path 整体小写（会同时将百分号编码中的字母转为小写，如 %2F -> %2f）
    path = parsed.path.lower()
    # params, query, fragment 也可按需小写
    params = parsed.params.lower()
    query = parsed.query.lower()
    fragment = parsed.fragment.lower()

    # 重建 URL，不保留原大小写
    normalized = urlunparse((scheme, netloc, path, params, query, fragment))
    # 去掉末尾的斜杠（仅当路径不为空且不是根目录 "/" 时）
    if normalized.endswith('/') and len(normalized) > 1:
        normalized = normalized.rstrip('/')
    return normalized
