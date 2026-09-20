# Daily Trends to Discord

매일 아침 **KST 09:00**에 10개국 Google Trends 일일 급상승 검색어를 모아
Discord 채널로 보내는 자동화.

- `trends_to_discord.py` — Google Trends 일일 급상승 RSS(`https://trends.google.com/trending/rss?geo=XX`)를
  파싱해 Discord 웹훅으로 임베드 전송. **표준 라이브러리만** 사용.
- `.github/workflows/daily-trends.yml` — 매일 00:00 UTC(= 09:00 KST) 실행 + 수동 실행.

## 대상 국가 (10개국)

🇰🇷 KR · 🇺🇸 US · 🇯🇵 JP · 🇬🇧 GB · 🇩🇪 DE · 🇫🇷 FR · 🇮🇳 IN · 🇧🇷 BR · 🇨🇦 CA · 🇦🇺 AU

## 환경 변수

| 변수 | 설명 |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | Discord 웹훅 URL. `DRY_RUN=1`이 아니면 필수 |
| `DRY_RUN` | `1`이면 전송하지 않고 콘솔에만 출력 |
| `TREND_GEOS` | 국가 코드 직접 지정 (예: `KR,US,JP`). 없으면 기본 10개국 |
| `TOP_N` | 국가별 키워드 개수 (기본 10) |

웹훅 URL은 **절대 코드나 커밋에 넣지 않는다.** 로컬에선 환경변수,
GitHub Actions에선 저장소 Secret(`DISCORD_WEBHOOK_URL`)으로만 다룬다.

## 로컬 실행

```bash
# 1) 파싱만 확인 (전송 없음)
DRY_RUN=1 python3 trends_to_discord.py

# 2) 실제 전송 1회
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python3 trends_to_discord.py
```

셸 히스토리에 URL을 남기고 싶지 않다면 명령 앞에 공백 한 칸을 넣거나
`.env`(gitignore 처리됨)에 넣고 `set -a; . ./.env; set +a` 로 불러온다.

## GitHub Actions 설정

```bash
# Secret 등록 (값은 프롬프트로 입력 → 히스토리에 안 남음)
gh secret set DISCORD_WEBHOOK_URL

# 수동 실행 & 확인
gh workflow run "Daily Trends to Discord"
gh run watch

# 전송 없이 파싱만 테스트
gh workflow run "Daily Trends to Discord" -f dry_run=true
```

## 스케줄 주의사항

- cron은 **UTC 기준**이다. `0 0 * * *` = 매일 09:00 KST.
- GitHub의 스케줄 실행은 러너가 붐빌 때 수 분~수십 분 지연될 수 있다.
- **60일간 저장소에 커밋이 없으면 GitHub가 스케줄 워크플로를 자동 비활성화한다.**
  그때는 저장소 **Actions 탭 → 해당 워크플로 → Enable workflow** 를 눌러 다시 켜야 한다.
  (알림 메일이 오며, 주기적으로 커밋을 남겨두면 예방된다.)

## 동작 방식 / 장애 처리

- 국가별로 RSS를 받아 `item` → 키워드, `ht:approx_traffic`, 대표 뉴스 링크를 뽑는다.
- 한 국가가 실패해도 나머지는 계속 진행하고, 해당 임베드에 실패 사유를 표시한다.
- Discord 제한(임베드 10개/메시지, 6000자/메시지)을 넘지 않도록
  임베드 5개씩 나눠 보내고 설명은 1000자로 잘라낸다.
- HTTP 429를 받으면 `retry_after` 만큼 기다렸다 1회 재시도한다.
- 모든 국가가 실패하면 전송하지 않고 실패 종료(exit 1)한다.
