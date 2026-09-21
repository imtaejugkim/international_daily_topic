# 세계 트렌드 → 디스코드

6개국의 뉴스·검색어·앱차트·앱리뷰를 매일 모아서, **읽어낸 결과**를 디스코드로 보낸다.
순위표를 그대로 옮기는 게 목적이 아니라, 여러 나라에 반복되는 주제를 찾아내고
그걸 근거로 서비스 아이디어를 뽑는 게 목적이다.

매일 **09:00 KST** 자동 실행.

## 대상 국가

🇰🇷 KR · 🇺🇸 US · 🇯🇵 JP · 🇬🇧 GB · 🇩🇪 DE · 🇧🇷 BR

iOS 점유율이 충분해서 앱차트가 그 나라 시장을 왜곡 없이 보여주는 곳으로 골랐다.
Google Play는 공식 무료 API가 없어 앱 데이터는 iOS만 본다. 안드로이드 비중이
압도적인 나라(인도 등)를 넣으면 앱차트 신호가 실제 시장과 어긋난다.

## 구조

```
[수집]  조용히 data/ 에 저장
  ├─ news.py              Google News 헤드라인 (top/business/technology)
  ├─ trends_to_discord.py Google Trends 급상승 검색어
  └─ app_charts.py        앱스토어 무료 차트 + 상위 앱 1~2점 리뷰
                          + 어제 대비 신규 진입 / 급상승 / 국가 교차 신호

[해석]  .claude/skills/daily-brief/SKILL.md
        Claude Code Action이 data/ 를 읽고 brief.json 을 쓴다
  1. 반복 주제   여러 나라 헤드라인에 되풀이되는 것
  2. 나라별 상황 각 나라가 지금 뭐에 붙들려 있나
  3. 아이디어    1·2에 근거해서만

[전송]  send_brief.py  brief.json → 디스코드 임베드
```

수집 스크립트는 **표준 라이브러리만** 쓴다. 외부 패키지가 필요한 건 없다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `news.py` | Google News RSS 6개국 × 3섹션. 본문은 안 주고 헤드라인만 준다 |
| `trends_to_discord.py` | Google Trends 급상승 RSS. 디스코드 전송 유틸(`post`/`chunk`/`clip`)도 여기 있다 |
| `app_charts.py` | Apple 차트 + 리뷰 수집, 어제 대비 비교, 신호 계산 |
| `send_brief.py` | `brief.json`을 임베드로 렌더링해 전송하고 `data/briefs/`에 보관 |
| `korean.py` | 원본 덤프용 한글 표기. **Anthropic API 키가 있을 때만** 동작, 없으면 원문 그대로 |
| `tools/probe_sources.py` | 새 데이터 소스가 살아있는지 CI에서 확인하는 용도 |
| `.claude/skills/daily-brief/SKILL.md` | **분석 지시문. 브리프 품질은 이 파일을 고쳐서 조정한다** |

## 쌓이는 데이터

```
data/news/2026-09-21.json      국가별 헤드라인
data/trends/2026-09-21.json    국가별 급상승 검색어
data/charts/2026-09-21.json    국가별 앱 차트
data/reviews/2026-09-21.json   상위 앱 1~2점 리뷰
data/briefs/2026-09-21.json    그날 브리프
```

**이 폴더는 의도적으로 커밋한다.** 어제 파일이 있어야 "신규 진입"과 "급상승"을
계산할 수 있고, 매일 커밋이 생기니 아래 60일 자동 비활성화도 같이 막힌다.

## Secrets

| 이름 | 필수 | 용도 |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | ✅ | 전송 대상 웹훅 |
| `CLAUDE_CODE_OAUTH_TOKEN` | ✅ | 브리프 작성. **Claude 구독으로 실행되므로 API 요금이 따로 안 나간다** |
| `ANTHROPIC_API_KEY` | ❌ | `korean.py`만 쓴다. 없으면 원본 덤프에 한글 표기가 안 붙는다 |

`CLAUDE_CODE_OAUTH_TOKEN`은 로컬에 Claude Code를 설치한 뒤 `claude setup-token`으로 만든다.
Console API 키(`sk-ant-...`)와는 **별개의 결제**다. OAuth 토큰은 구독을 쓰고, API 키는 종량제다.

웹훅 URL과 토큰은 **절대 코드나 커밋에 넣지 않는다.** Secret으로만 다룬다.

등록: 저장소 → Settings → Secrets and variables → Actions → New repository secret

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DRY_RUN` | — | `1`이면 전송·저장·커밋 없이 콘솔 출력만 |
| `SEND_RAW` | `1` | `0`이면 원본 덤프(검색어·앱차트)를 안 보낸다. **데이터는 그래도 저장된다** |
| `TREND_GEOS` | 6개국 | 검색어 대상 국가 (`KR,US,JP`) |
| `TOP_N` | `10` | 국가별 검색어 개수 |
| `NEWS_GEOS` | 6개국 | 뉴스 대상 국가 |
| `NEWS_PER_FEED` | `40` | 피드당 헤드라인 개수 |
| `CHART_GEOS` | 6개국 | 앱차트 대상 국가 (소문자: `kr,us,jp`) |
| `CHART_SIZE` | `25` | 국가별 앱 개수 |
| `REVIEW_APPS` | `10` | 국가별로 리뷰를 긁을 상위 앱 개수 |
| `BRIEF_PATH` | `brief.json` | 브리프 파일 경로 |

브리프가 자리를 잡으면 `SEND_RAW`를 `'0'`으로 바꾸는 걸 권한다.
원본은 `data/`에 남으니 언제든 볼 수 있고, 디스코드는 해석만 받게 된다.

## 로컬 실행

```bash
# 수집만 확인 (전송·저장 없음)
DRY_RUN=1 python3 news.py
DRY_RUN=1 python3 trends_to_discord.py
DRY_RUN=1 CHART_GEOS=kr REVIEW_APPS=3 python3 app_charts.py

# 이미 있는 brief.json 렌더링만 확인
DRY_RUN=1 python3 send_brief.py
```

브리프 작성 자체는 Claude Code Action이 하므로 로컬에서는 `/daily-brief` 스킬을
직접 실행하면 된다.

## 워크플로

`.github/workflows/daily-trends.yml` — 매일 00:00 UTC(= 09:00 KST) + 수동 실행.
수동 실행 시 `dry_run` 입력을 켜면 수집만 하고 전송·커밋을 건너뛴다.

`.github/workflows/probe.yml` — 새 데이터 소스를 붙이기 전에 러너에서 응답 형태를
확인하는 용도. 필요할 때만 수동 실행.

### 브리프 단계에 `github_token`을 넘기는 이유

Claude Code Action은 기본적으로 Claude GitHub App으로 인증한다. 그 앱이 저장소에
설치돼 있지 않으면 `401 Claude Code is not installed on this repository`로 실패한다.
이 단계는 `data/`를 읽고 `brief.json`을 쓸 뿐 GitHub API를 쓰지 않으므로,
워크플로 기본 토큰을 넘겨 앱 인증 교환 자체를 건너뛴다. 앱 설치가 필요 없다.

## 스케줄 주의사항

- cron은 **UTC 기준**이다. `0 0 * * *` = 매일 09:00 KST.
- 스케줄 워크플로는 **기본 브랜치에서만** 돈다.
- 러너가 붐비면 수 분~수십 분 지연될 수 있다. 정시 보장이 아니다.
- **60일간 커밋이 없으면 GitHub가 스케줄을 자동 비활성화한다.** 알림 메일이 오며,
  Actions 탭 → 해당 워크플로 → **Enable workflow**로 다시 켠다.
  이 저장소는 매일 `data/`를 커밋하므로 정상 동작 중이면 걸릴 일이 없다.

## 설계 메모

**앱을 국가 간에 맞출 땐 이름이 아니라 App Store `id`, 카테고리는 이름이 아니라 `genreId`를 쓴다.**
차트 응답이 각 나라 언어로 오기 때문이다. 이름으로 맞추면 같은 앱이
`Duolingo: Sprachen und Schach`(독일)와 `Duolingo-英語/韓国語などの...`(일본)로
서로 다른 앱이 되고, 카테고리를 이름으로 비교하면 `금융`과 `ファイナンス`가 달라서
차집합이 항상 전체가 된다.

**Google News는 헤드라인만 주고 본문은 안 준다.** 그게 오히려 맞다. 알고 싶은 건
기사 하나의 디테일이 아니라 그 나라 언론이 어떤 주제로 반복해서 돌아오는가이고,
하루 수백 개 헤드라인이면 그 패턴이 더 선명하다.

**Apple은 연속 호출을 조인다.** 504와 read timeout이 난다. 요청 간격을 두고
실패 시 백오프 재시도한다.

**Discord 한도**: 메시지당 임베드 10개, 6000자. 임베드 설명은 1900자로 자르고,
메시지는 개수가 아니라 **실측 길이 기준**으로 묶는다(`chunk()`). 최악의 경우에도
한 메시지가 5500자를 넘지 않는다.

**한 나라가 실패해도 나머지는 계속 간다.** 모든 나라가 실패했을 때만 전송하지 않고
exit 1로 끝낸다. 브리프 단계가 실패해도 수집분은 그대로 저장·커밋된다.

**HTTP 429**는 `retry_after`만큼 기다렸다 1회 재시도한다.
