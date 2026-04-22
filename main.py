import os
import json
import smtplib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── 환경변수 ──────────────────────────────────────────────
OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
GMAIL_USER      = os.environ["GMAIL_USER"]
GMAIL_APP_PW    = os.environ["GMAIL_APP_PW"]
TO_EMAIL        = os.environ["TO_EMAIL"]
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]


# ── 1. YouTube 트렌딩 F&B 영상 수집 ──────────────────────
def fetch_youtube_trends():
    queries = ["viral food 2025", "viral snack tiktok", "trending drink recipe", "new food product review"]
    results = []

    for q in queries:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": q,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxResults": 2,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get("items", []):
                vid_id  = item["id"].get("videoId", "")
                title   = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]
                pub     = item["snippet"]["publishedAt"][:10]
                link    = f"https://www.youtube.com/watch?v={vid_id}"
                results.append(f"- [{title}] ({channel}, {pub})\n  {link}")
        except Exception as e:
            results.append(f"[YouTube 오류: {q}] {e}")

    return "\n".join(results) if results else "YouTube 데이터 없음"


# ── 2. Reddit 트렌드 수집 ─────────────────────────────────
def fetch_reddit_trends():
    subreddits = ["food", "snacks", "DessertPorn", "cocktails", "foodtrends"]
    results = []

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/top/.json?limit=5&t=week"
        req = urllib.request.Request(url, headers={"User-Agent": "FnbTrendBot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            for post in data["data"]["children"][:2]:
                p = post["data"]
                results.append(
                    f"- [{p['title']}] (👍{p['ups']:,})\n"
                    f"  https://reddit.com{p['permalink']}"
                )
        except Exception as e:
            results.append(f"[Reddit 오류: r/{sub}] {e}")

    return "\n".join(results) if results else "Reddit 데이터 없음"


# ── 3. 식품 전문 미디어 RSS (인스타/틱톡 트렌드 반영) ────
def fetch_food_media_rss():
    feeds = [
        ("Eater",       "https://www.eater.com/rss/index.xml"),
        ("Food52",      "https://food52.com/blog/feed"),
        ("Bon Appétit", "https://www.bonappetit.com/feed/rss"),
        ("Delish",      "https://www.delish.com/rss/all.xml/"),
    ]
    results = []

    for name, url in feeds:
        req = urllib.request.Request(url, headers={"User-Agent": "FnbTrendBot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # RSS 2.0 형식
            items = root.findall(".//item")
            if items:
                for item in items[:2]:
                    title = item.findtext("title", "").strip()
                    link  = item.findtext("link", "").strip()
                    if title and link:
                        results.append(f"- [{name}] {title}\n  {link}")
            else:
                # Atom 형식
                entries = root.findall(".//atom:entry", ns) or root.findall(".//entry")
                for entry in entries[:2]:
                    title = entry.findtext("atom:title", entry.findtext("title", ""), ns).strip()
                    link_el = entry.find("atom:link", ns) or entry.find("link")
                    link = link_el.get("href", "") if link_el is not None else ""
                    if title and link:
                        results.append(f"- [{name}] {title}\n  {link}")
        except Exception as e:
            results.append(f"[RSS 오류: {name}] {e}")

    return "\n".join(results) if results else "식품 미디어 데이터 없음"


# ── 4. TikTok 트렌드 키워드 (Google Trends 우회) ─────────
def fetch_tiktok_trends():
    """
    TikTok 공식 API 접근 불가로,
    TikTok 바이럴 콘텐츠를 주로 다루는 YouTube 검색으로 대체 수집
    """
    queries = ["tiktok food trend", "tiktok viral recipe", "tiktok snack review"]
    results = []

    for q in queries:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": q,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxResults": 2,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get("items", []):
                vid_id  = item["id"].get("videoId", "")
                title   = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]
                pub     = item["snippet"]["publishedAt"][:10]
                link    = f"https://www.youtube.com/watch?v={vid_id}"
                results.append(f"- [{title}] ({channel}, {pub})\n  {link}")
        except Exception as e:
            results.append(f"[TikTok 트렌드 오류: {q}] {e}")

    return "\n".join(results) if results else "TikTok 트렌드 데이터 없음"


# ── 5. OpenAI로 통합 리포트 생성 ─────────────────────────
def generate_report(youtube_raw, reddit_raw, media_raw, tiktok_raw) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    prompt = f"""
당신은 글로벌 F&B 트렌드 전문 애널리스트입니다.
아래 이번 주 수집된 다양한 해외 채널(YouTube, TikTok, Instagram 계열 식품 미디어, Reddit)의
원시 데이터를 바탕으로, 한국 제과·스낵 마케터를 위한 주간 트렌드 리포트를 작성해 주세요.

[수집일: {today}]

=== YouTube 트렌딩 F&B 영상 ===
{youtube_raw}

=== TikTok 바이럴 트렌드 (YouTube 경유 수집) ===
{tiktok_raw}

=== 해외 식품 전문 미디어 (Eater·Food52·Bon Appétit·Delish) ===
{media_raw}

=== Reddit 인기 포스트 ===
{reddit_raw}

---
아래 형식으로 한국어 리포트를 작성해 주세요.

## 🌍 이번 주 해외 F&B 트렌드 리포트 ({today})

### 📌 핵심 트렌드 요약 (3줄)
(이번 주 가장 두드러진 트렌드를 채널을 아우르며 3문장으로 압축)

### 🔥 채널별 바이럴 신제품 / 레시피 TOP 6
각 항목마다 아래 형식으로 작성:
- **제품명/레시피명**
  - 주요 채널: (YouTube / TikTok / Instagram / Reddit 중)
  - 링크:
  - 바이럴 요인: (왜 퍼졌는지 2~3문장 분석)
  - 한국 제과 시장 적용 포인트:

### 📱 채널별 트렌드 온도
- **TikTok/Instagram**: 이번 주 주목할 키워드와 분위기
- **YouTube**: 주요 포맷과 콘텐츠 패턴
- **해외 식품 미디어**: 에디터픽 트렌드 요약
- **Reddit 커뮤니티**: 소비자 반응과 화제

### 💡 마케터 인사이트
(한국 스낵·제과 신제품 기획에 바로 활용할 수 있는 시사점 3가지)

### 📎 원본 링크 모음
(위에서 언급된 링크를 채널별로 정리)
"""

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 2500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ── 6. 이메일 발송 ────────────────────────────────────────
def send_email(report: str):
    today = datetime.now().strftime("%Y.%m.%d")
    subject = f"[F&B 트렌드 리포트] {today} 주간 해외 트렌드"

    html_body = "<html><body style='font-family:sans-serif;line-height:1.7;max-width:700px;margin:auto;padding:24px'>"
    for line in report.split("\n"):
        if line.startswith("## "):
            html_body += f"<h2 style='color:#1a1a2e'>{line[3:]}</h2>"
        elif line.startswith("### "):
            html_body += f"<h3 style='color:#e94560;border-bottom:1px solid #eee;padding-bottom:4px'>{line[4:]}</h3>"
        elif line.startswith("- **"):
            html_body += f"<p><b>{line[4:]}</b></p>"
        elif line.startswith("- "):
            html_body += f"<li>{line[2:]}</li>"
        elif line.strip() == "":
            html_body += "<br>"
        else:
            html_body += f"<p>{line}</p>"
    html_body += "</body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(report, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PW)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())

    print(f"✅ 이메일 발송 완료 → {TO_EMAIL}")


# ── 메인 ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("📡 YouTube 트렌드 수집 중...")
    youtube_data = fetch_youtube_trends()

    print("📡 TikTok 트렌드 수집 중...")
    tiktok_data  = fetch_tiktok_trends()

    print("📡 식품 전문 미디어 RSS 수집 중...")
    media_data   = fetch_food_media_rss()

    print("📡 Reddit 트렌드 수집 중...")
    reddit_data  = fetch_reddit_trends()

    print("🤖 GPT 리포트 생성 중...")
    report = generate_report(youtube_data, reddit_data, media_data, tiktok_data)
    print(report)

    print("📧 이메일 발송 중...")
    send_email(report)
