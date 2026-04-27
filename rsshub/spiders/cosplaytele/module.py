from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, urlunparse
import requests
import datetime
from rsshub.utils import DEFAULT_HEADERS,fetch
from parsel import Selector

domain_url = "https://cosplaytele.com"


# get every post
def parse(post:Selector):
    item = {}
    a_tag = post.find("a")
    if a_tag:
        item['title'] = a_tag.get('aria-label')   # 获取标题文本
        item['link'] = normalize_url(a_tag.get('href'))             # 获取链接地址
        
    print(item['title'], item['link'])

    
    item['author'] = 'unknown'
    item['pubDate'] = datetime.datetime.now().time() # 这里需要根据实际情况解析发布时间
    
    res = requests.get(item['link'], headers=DEFAULT_HEADERS)
    soup = BeautifulSoup(res.text, 'html.parser')
    figures = soup.find(id="gallery-1").find_all("figure")
    
    img_urls = []
    for figure in figures:
        img_urls.append(figure.find("a").get("href"))
    print(img_urls)
    
    description = "<div>"
    for img_url in img_urls:
        description += f'<img src="{img_url}" />\n'
    description += "</div>"
    item['description'] = description  # 将修改后的HTML转换为字符串


    return item
    
# get content index ,max 12,category:cosplay-ero,nude,cosplay
def ctx(category:str="cosplay"):

    url = url_builder(category)
    print(f"fetching {url} ...")
    res = requests.get(url, headers=DEFAULT_HEADERS)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    
    posts = soup.find(id="post-list").find_all("div",class_="col post-item")
   
    print(f"total {len(posts)} posts found.")


    # posts = posts_ if len(posts_) < 1 else posts_[:1]
    posts = posts[:12]
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
 
