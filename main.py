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

# 조회수 필터 기준
MIN_VIEW_COUNT = 100_000


# ── 1. YouTube 영상 ID 수집 ───────────────────────────────
def search_youtube_video_ids(queries, days=30, max_per_query=10):
    """키워드별로 최근 N일 이내 영상 ID 수집"""
    video_ids = []
    published_after = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for q in queries:
        params = urllib.parse.urlencode({
            "part": "id",
            "q": q,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": published_after,
            "maxResults": max_per_query,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get("items", []):
                vid_id = item["id"].get("videoId")
                if vid_id and vid_id not in video_ids:
                    video_ids.append(vid_id)
        except Exception as e:
            print(f"[YouTube 검색 오류: {q}] {e}")

    return video_ids


# ── 2. YouTube 조회수 가져와서 필터링 ────────────────────
def fetch_youtube_viral(video_ids, min_views=MIN_VIEW_COUNT):
    """video IDs에서 실제 조회수 조회 후 기준 이상만 반환"""
    results = []
    # YouTube API는 한 번에 최대 50개 조회 가능
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        params = urllib.parse.urlencode({
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/videos?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get("items", []):
                views = int(item.get("statistics", {}).get("viewCount", 0))
                if views >= min_views:
                    vid_id  = item["id"]
                    title   = item["snippet"]["title"]
                    channel = item["snippet"]["channelTitle"]
                    pub     = item["snippet"]["publishedAt"][:10]
                    link    = f"https://www.youtube.com/watch?v={vid_id}"
                    results.append({
                        "title": title,
                        "channel": channel,
                        "pub": pub,
                        "views": views,
                        "link": link,
                    })
        except Exception as e:
            print(f"[YouTube 상세 조회 오류] {e}")

    # 조회수 내림차순 정렬
    results.sort(key=lambda x: x["views"], reverse=True)
    return results


def format_youtube(items, label="YouTube"):
    if not items:
        return f"{label} 데이터 없음 (조회수 {MIN_VIEW_COUNT:,} 미만)"
    lines = []
    for v in items[:10]:  # 상위 10개만 GPT에 전달
        views_str = f"{v['views']:,}"
        lines.append(
            f"- [{v['title']}] ({v['channel']}, {v['pub']}, 조회수 {views_str})\n"
            f"  {v['link']}"
        )
    return "\n".join(lines)


# ── 3. 일반 YouTube 트렌드 수집 (바이럴 F&B 키워드) ──────
def fetch_youtube_trends():
    queries = [
        "viral food tiktok 2026",
        "trending snack 2026",
        "food that went viral",
        "new snack review viral",
        "viral recipe this week",
        "viral drink recipe",
        "new food product try",
        "mukbang new snack",
    ]
    ids = search_youtube_video_ids(queries, days=30, max_per_query=10)
    items = fetch_youtube_viral(ids, min_views=MIN_VIEW_COUNT)
    return format_youtube(items, "YouTube")


# ── 4. TikTok 바이럴 트렌드 (YouTube 경유) ───────────────
def fetch_tiktok_trends():
    queries = [
        "tiktok food trend viral",
        "tiktok snack recipe popular",
        "tiktok viral recipe remake",
        "tiktok what i eat",
    ]
    ids = search_youtube_video_ids(queries, days=30, max_per_query=10)
    items = fetch_youtube_viral(ids, min_views=MIN_VIEW_COUNT)
    return format_youtube(items, "TikTok 경유")


# ── 5. 식품 전문 미디어 RSS ───────────────────────────────
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

            items = root.findall(".//item")
            if items:
                for item in items[:2]:
                    title = item.findtext("title", "").strip()
                    link  = item.findtext("link", "").strip()
                    if title and link:
                        results.append(f"- [{name}] {title}\n  {link}")
            else:
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


# ── 6. Reddit 트렌드 수집 ─────────────────────────────────
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


# ── 7. OpenAI로 통합 리포트 생성 ─────────────────────────
def generate_report(youtube_raw, tiktok_raw, media_raw, reddit_raw) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    prompt = f"""
당신은 글로벌 F&B 트렌드 전문 애널리스트입니다.
아래는 이번 주 해외 소셜미디어에서 실제로 조회수 10만 이상을 기록한 영상과
식품 전문 미디어, Reddit 커뮤니티에서 수집한 원시 데이터입니다.

한국 제과·스낵 마케터를 위한 주간 트렌드 리포트를 작성해 주세요.

[수집일: {today}]

=== YouTube 바이럴 F&B 영상 (조회수 10만+ 필터링) ===
{youtube_raw}

=== TikTok 바이럴 트렌드 (YouTube 경유, 조회수 10만+) ===
{tiktok_raw}

=== 해외 식품 전문 미디어 (Eater·Food52·Bon Appétit·Delish) ===
{media_raw}

=== Reddit 인기 포스트 ===
{reddit_raw}

---
아래 형식으로 한국어 리포트를 작성해 주세요.

## 🌍 이번 주 해외 F&B 트렌드 리포트 ({today})

### 📌 핵심 트렌드 요약 (3줄)
이번 주 가장 뜨거운 트렌드를 3문장으로 압축. 반드시 실제 데이터 기반으로 작성.

### 🔥 이번 주 바이럴 TOP 6
조회수와 반응이 높은 순으로 선정. 각 항목:
- **제품명/레시피명**
  - 채널/출처:
  - 조회수/반응:
  - 링크:
  - 바이럴 요인: (왜 이게 퍼졌는지 구체적으로 2~3문장 분석)
  - 한국 제과 시장 적용 포인트:

### 📱 채널별 트렌드 온도
- **TikTok/Instagram**: 이번 주 핵심 키워드와 콘텐츠 패턴
- **YouTube**: 주목할 포맷과 반응 패턴
- **해외 식품 미디어**: 에디터픽 트렌드
- **Reddit 커뮤니티**: 소비자 반응과 화제

### 💡 마케터 인사이트
한국 스낵·제과 신제품 기획에 바로 쓸 수 있는 시사점 3가지.
각 시사점은 구체적인 제품 아이디어나 캠페인 방향까지 포함.

### 📎 원본 링크 모음
채널별로 정리.
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


# ── 8. 이메일 발송 ────────────────────────────────────────
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
    print("📡 YouTube 바이럴 트렌드 수집 중 (조회수 10만+ 필터)...")
    youtube_data = fetch_youtube_trends()
    print(youtube_data[:300])

    print("📡 TikTok 트렌드 수집 중...")
    tiktok_data  = fetch_tiktok_trends()
    print(tiktok_data[:300])

    print("📡 식품 전문 미디어 RSS 수집 중...")
    media_data   = fetch_food_media_rss()

    print("📡 Reddit 트렌드 수집 중...")
    reddit_data  = fetch_reddit_trends()

    print("🤖 GPT 리포트 생성 중...")
    report = generate_report(youtube_data, tiktok_data, media_data, reddit_data)
    print(report)

    print("📧 이메일 발송 중...")
    send_email(report)
