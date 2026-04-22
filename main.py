import os
import anthropic
import smtplib
import json
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── 환경변수 ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER        = os.environ["GMAIL_USER"]        # 발신 Gmail 주소
GMAIL_APP_PW      = os.environ["GMAIL_APP_PW"]      # Gmail 앱 비밀번호
TO_EMAIL          = os.environ["TO_EMAIL"]          # 수신 이메일
YOUTUBE_API_KEY   = os.environ["YOUTUBE_API_KEY"]   # YouTube Data API v3 키

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── 1. YouTube 트렌딩 F&B 영상 수집 ──────────────────────
def fetch_youtube_trends():
    queries = ["food trend 2025", "viral snack", "new food viral", "trending drink recipe"]
    results = []

    for q in queries:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": q,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxResults": 3,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            for item in data.get("items", []):
                vid_id = item["id"].get("videoId", "")
                title  = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]
                pub    = item["snippet"]["publishedAt"][:10]
                link   = f"https://www.youtube.com/watch?v={vid_id}"
                results.append(f"- [{title}] ({channel}, {pub})\n  {link}")
        except Exception as e:
            results.append(f"[YouTube 수집 오류: {q}] {e}")

    return "\n".join(results) if results else "YouTube 데이터 없음"


# ── 2. Reddit RSS 수집 ────────────────────────────────────
def fetch_reddit_trends():
    subreddits = ["food", "snacks", "DessertPorn", "cocktails"]
    results = []

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/top/.json?limit=5&t=week"
        req = urllib.request.Request(url, headers={"User-Agent": "FnbTrendBot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            for post in data["data"]["children"][:3]:
                p = post["data"]
                results.append(
                    f"- [{p['title']}] (👍{p['ups']:,})\n"
                    f"  https://reddit.com{p['permalink']}"
                )
        except Exception as e:
            results.append(f"[Reddit 수집 오류: r/{sub}] {e}")

    return "\n".join(results) if results else "Reddit 데이터 없음"


# ── 3. Claude API로 분석 리포트 생성 ─────────────────────
def generate_report(youtube_raw: str, reddit_raw: str) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    prompt = f"""
당신은 글로벌 F&B 트렌드 전문 애널리스트입니다.
아래 이번 주 수집된 해외 소셜미디어(YouTube·Reddit) 원시 데이터를 바탕으로,
한국 제과·스낵 마케터를 위한 주간 트렌드 리포트를 작성해 주세요.

[수집일: {today}]

=== YouTube 트렌딩 영상 ===
{youtube_raw}

=== Reddit 인기 포스트 ===
{reddit_raw}

---
아래 형식으로 한국어 리포트를 작성해 주세요.

## 🌍 이번 주 해외 F&B 트렌드 리포트 ({today})

### 📌 핵심 트렌드 요약 (3줄)
(이번 주 가장 두드러진 트렌드를 3문장으로 압축)

### 🔥 바이럴 신제품 / 레시피 TOP 5
각 항목마다:
- **제품명/레시피명**
  - 채널/출처:
  - 링크:
  - 바이럴 요인: (왜 퍼졌는지 2~3문장 분석)
  - 한국 제과 시장 적용 포인트:

### 💡 마케터 인사이트
(한국 스낵·제과 신제품 기획에 바로 활용할 수 있는 시사점 3가지)

### 📎 원본 링크 모음
(위에서 언급된 링크를 한곳에 정리)
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── 4. 이메일 발송 ────────────────────────────────────────
def send_email(report: str):
    today = datetime.now().strftime("%Y.%m.%d")
    subject = f"[F&B 트렌드 리포트] {today} 주간 해외 트렌드"

    # HTML 변환 (마크다운 헤더/볼드 기본 처리)
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

    print("📡 Reddit 트렌드 수집 중...")
    reddit_data  = fetch_reddit_trends()

    print("🤖 Claude 리포트 생성 중...")
    report = generate_report(youtube_data, reddit_data)
    print(report)

    print("📧 이메일 발송 중...")
    send_email(report)
