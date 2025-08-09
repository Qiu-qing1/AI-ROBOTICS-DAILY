# -*- coding: utf-8 -*-
import os, re, time, html
from datetime import datetime, timezone
from urllib.parse import urlencode

import feedparser
import requests
from dateutil import parser as dtparser

UTC = timezone.utc

# ===== 你可以在这里增减 RSS 源 =====
FEEDS = [
    # --- 研究论文 ---
    "http://export.arxiv.org/rss/cs.AI",   # arXiv: Artificial Intelligence（官方RSS）
    "http://export.arxiv.org/rss/cs.RO",   # arXiv: Robotics（官方RSS）

    # --- 官方博客 / 厂商 ---
    "https://blog.google/technology/google-deepmind/rss/",  # Google DeepMind（页面提供RSS入口）
    "https://blog.google/technology/ai/rss/",               # Google AI（技术栏目RSS）
    "https://ai.meta.com/blog/rss.xml",                     # Meta AI（若失效可用 RSSHub 或改为站点抓取）
    "https://openai.com/blog/rss.xml",                      # OpenAI Blog（有社区确认RSS）
    "https://nvidianews.nvidia.com/rss",                    # NVIDIA 新闻稿RSS
    # 也可：NVIDIA 技术博客分类 RSS（若可用）: https://blogs.nvidia.com/blog/category/robotics/feed/

    # --- 行业媒体 / 机器人 ---
    "https://spectrum.ieee.org/rss/robotics/fulltext",      # IEEE Spectrum Robotics（全文RSS）
    "https://www.therobotreport.com/feed",                  # The Robot Report
]

# 关键词用于 GitHub Trending 过滤
KEYWORDS = [
    r"\bAI\b", r"\bLLM\b", r"robot", r"robotic", r"reinforcement learning",
    r"machine learning", r"deep learning", r"foundation model", r"autonomous",
    r"ROS\b", r"SLAM\b", r"sim2real", r"manipulation", r"quadruped"
]
KEY_RE = re.compile("|".join(KEYWORDS), re.I)

# GitHub API（可选）：用于获取仓库 topics 更精准过滤
GH_TOKEN = os.getenv("GH_TOKEN", "").strip()

def normalize_dt(d):
    if not d:
        return None
    try:
        return dtparser.parse(d).astimezone(UTC)
    except Exception:
        return None

def fetch_feed(url, limit=40):
    try:
        data = feedparser.parse(url)
        items = []
        for e in data.entries[:limit]:
            title = html.unescape(getattr(e, "title", "") or "").strip()
            link  = getattr(e, "link", "") or ""
            summary = html.unescape(getattr(e, "summary", "") or "")\
                      .replace("\n", " ").strip()
            published = normalize_dt(getattr(e, "published", None) or getattr(e, "updated", None))
            items.append({
                "source": url,
                "title": title,
                "link": link,
                "summary": summary,
                "published": published or datetime.now(UTC),
            })
        return items
    except Exception as ex:
        return []

def gh_get(url):
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ai-robotics-daily"}
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_trending_filtered(since="daily", limit=50, want=20):
    """
    抓 GitHub Trending（全站），再用关键词/Topic 过滤到 AI/机器人相关
    """
    base = "https://github.com/trending"
    r = requests.get(base, params={"since": since}, timeout=30,
                     headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    html_txt = r.text

    # 简单解析 trending 列表
    rows = re.findall(r'<article[^>]*class="Box-row"[^>]*>(.*?)</article>', html_txt, flags=re.S)
    repos = []
    for row in rows[:limit]:
        m = re.search(r'href="/([^/]+/[^"]+)"', row)
        if not m: 
            continue
        full = m.group(1)  # owner/name
        href = f"https://github.com/{full}"
        desc = ""
        md = re.search(r'<p[^>]*>(.*?)</p>', row, flags=re.S)
        if md:
            desc = re.sub("<.*?>", "", md.group(1)).strip()
        repos.append({"full": full, "url": href, "desc": desc})

    results = []
    for rp in repos:
        hit = bool(KEY_RE.search(rp["full"])) or bool(KEY_RE.search(rp["desc"]))
        # 如果有 GH_TOKEN，再用 topics 过滤一次
        if GH_TOKEN:
            try:
                topics = gh_get(f"https://api.github.com/repos/{rp['full']}/topics").get("names", [])
                if any(KEY_RE.search(t) for t in topics):
                    hit = True
            except Exception:
                pass
        if hit:
            results.append(rp)
        if len(results) >= want:
            break
    return results

def build_markdown():
    now = datetime.now(UTC)
    title = f"# AI & 机器人 技术热点日报（{now.strftime('%Y-%m-%d %H:%M UTC')}）\n"
    intro = (
        "\n> 来源包含：arXiv（cs.AI/cs.RO）、OpenAI/DeepMind/Google/Meta/NVIDIA、IEEE Spectrum Robotics、"
        "The Robot Report 等官方/媒体 RSS，以及按关键词/Topic 过滤的 GitHub Trending。\n\n"
    )

    # 1) 聚合 RSS
    feed_items = []
    for u in FEEDS:
        feed_items.extend(fetch_feed(u, limit=40))
        time.sleep(0.5)  # 轻微限速

    # 去重 & 按时间排序
    seen = set()
    uniq = []
    for it in feed_items:
        key = (it["title"][:120], it["link"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda x: x["published"] or datetime(1970,1,1, tzinfo=UTC), reverse=True)

    # 2) GitHub Trending 过滤
    gh_daily  = fetch_trending_filtered("daily", want=20)
    gh_weekly = fetch_trending_filtered("weekly", want=20)

    def section_rss(maxn=40):
        md = ["## 📡 最新资讯（RSS 聚合）\n",
              "| 时间(UTC) | 标题 | 来源 |\n",
              "|---|---|---|\n"]
        for it in uniq[:maxn]:
            src = it["source"].split("/")[2]
            ts = (it["published"] or now).strftime("%Y-%m-%d %H:%M")
            title = it["title"].replace("|", "/")
            md.append(f"| {ts} | [{title}]({it['link']}) | {src} |")
        md.append("\n")
        return "\n".join(md)

    def section_trending(label, items):
        md = [f"## ⭐ GitHub Trending（{label}，AI/机器人过滤）\n",
              "| # | 仓库 | 简介 |\n",
              "|---:|---|---|\n"]
        for i, it in enumerate(items, 1):
            name = it["full"]
            desc = (it["desc"] or "-").replace("|","/").strip()
            md.append(f"| {i} | [{name}]({it['url']}) | {desc} |")
        md.append("\n")
        return "\n".join(md)

    parts = [
        title, intro,
        section_rss(60),
        section_trending("Daily", gh_daily),
        section_trending("Weekly", gh_weekly),
        "_自动生成 · 配置与脚本见 `ai_robotics_daily.py`。_\n"
    ]
    return "\n".join(parts)

def main():
    md = build_markdown()
    with open("AI_ROBOTICS_DAILY.md", "w", encoding="utf-8") as f:
        f.write(md)

if __name__ == "__main__":
    main()
