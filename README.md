# Steam 게임 트렌드 → 디스코드

매일 Steam에서 **무엇이 갑자기 떴는지**를 잡아내고, 왜 떴는지 조사해서,
**작은 팀이 만들 수 있는 게임 아이디어**로 바꿔 디스코드로 보낸다.

매일 **09:00 KST** 자동 실행.

## 왜 순위가 아니라 변화를 보는가

Counter-Strike는 53만 명, PUBG는 29만 명이다. 내일도 그렇고 다음 달에도 그렇다.
유저층이 굳은 게임의 절대 숫자에는 **정보가 없다.** 그걸 매일 보고하면 같은 말을 반복하게 된다.

정보는 변화에 있다. 어제 2,200명이던 게임이 오늘 22,000명이면 그게 신호다.
그래서 모든 게임을 **얼마나 큰지가 아니라 어떻게 움직였는지**로 분류하고,
굳어버린 거인들은 `settled_giants`라는 별도 칸에 모아 **무시 대상으로 표시**한다.

## 구조

```
[수집] steam_collect.py
  ├─ 동시접속 상위 100 (rank, last_week_rank)
  ├─ 신작 / 출시예정 / 인기 / 할인 목록
  └─ 감시 목록 전체의 정확한 동시접속 수   ← 급등 추적의 근거
        감시 목록 = 상위 100 ∪ 신작·예정 ∪ 전에 본 모든 게임

[신호] steam_signals.py
  🚀 surging    하루 +30% 이상
  🆕 new_entry  오늘 처음 등장
  📈 climbing   3일 연속 상승 (급등은 아님)
  📉 sinking    급락
  💤 settled_giants  무시 대상

[해석] .claude/skills/game-brief/SKILL.md
  Claude Code Action이 신호를 읽고 웹을 검색해 brief.json 을 쓴다
  1. 오늘 움직인 것 — 왜 움직였는지 검색으로 확인
  2. 읽히는 흐름   — 급등들의 공통점
  3. 만들 것 3갈래 — ride(올라타기) / twist(비틀기) / gap(빈자리)

[전송] send_brief.py → 디스코드
```

전부 **표준 라이브러리만** 쓴다. Steam API 키도 필요 없다 — 쓰는 엔드포인트가 전부 공개다.

## Steam 데이터 출처

| 엔드포인트 | 쓰임 | 키 |
| --- | --- | --- |
| `ISteamChartsService/GetMostPlayedGames` | 동시접속 상위 100 + 지난주 순위 | 불필요 |
| `ISteamUserStats/GetNumberOfCurrentPlayers` | **게임별 정확한 동시접속 수** | 불필요 |
| `store/api/featuredcategories` | 신작·출시예정·인기·할인 | 불필요 |
| `store/api/appdetails` | 장르·출시일·가격·개발사 | 불필요 |

`GetTopReleasesPages`는 데이터가 2025년 2월에 멈춰 있어 쓰지 않는다.
SteamSpy는 보유자 추정이 필요해지면 보조로 쓸 수 있다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `steam_collect.py` | 일일 스냅샷 수집 |
| `steam_signals.py` | **급등·신규·상승 판정.** 거인을 걸러내는 곳 |
| `send_brief.py` | `brief.json`을 임베드로 렌더링해 전송하고 `data/briefs/`에 보관 |
| `discord_post.py` | 디스코드 전송과 임베드 한도 처리 |
| `tools/probe_steam.py` | 엔드포인트가 살아있는지 CI에서 확인 |
| `tools/notify_failure.py` | 브리프 실패 시 디스코드 알림 |
| `.claude/skills/game-brief/SKILL.md` | **분석 지시문. 브리프 품질은 이 파일로 조정한다** |

## 쌓이는 데이터

```
data/steam/2026-11-17.json    그날 스냅샷 (동시접속 수 포함)
data/signals/2026-11-17.json  급등·신규·상승 판정 결과
data/briefs/2026-11-17.json   그날 브리프
data/games.json               게임별 장르·출시일·가격 (한 번만 조회해 재사용)
```

**이 폴더는 의도적으로 커밋한다.** 어제 숫자가 있어야 오늘 급등을 계산할 수 있다.

`archive-app-trends/`는 이전 프로젝트(국가별 앱·뉴스 트렌드)의 47일치 기록이다.
지금 파이프라인과는 무관하며 참고용으로만 남겨뒀다.

## Secrets

| 이름 | 필수 | 용도 |
| --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | ✅ | 전송 대상 웹훅 |
| `CLAUDE_CODE_OAUTH_TOKEN` | ✅ | 브리프 작성. **Claude 구독으로 실행되어 API 요금이 따로 안 나간다** |

`CLAUDE_CODE_OAUTH_TOKEN`은 로컬에서 `claude setup-token`으로 만든다.
Console API 키(`sk-ant-...`)와는 **별개의 결제**다. 이 토큰은 만료될 수 있고,
만료되면 브리프 단계가 2초 만에 실패한다 — 그때 디스코드로 알림이 간다.

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DRY_RUN` | — | `1`이면 전송·저장·커밋 없이 출력만 |
| `WATCH_LIMIT` | `220` | 동시접속을 조회할 게임 수 |
| `SURGE_PCT` | `30` | 하루 몇 % 오르면 급등으로 볼지 |
| `NOISE_FLOOR` | `500` | 이보다 적은 동시접속은 무시 (8명→80명은 +900%지만 의미 없다) |
| `SIGNAL_WINDOW` | `30` | 신호 계산에 쓸 과거 일수 |
| `BRIEF_PATH` | `brief.json` | 브리프 파일 경로 |

## 로컬 실행

```bash
DRY_RUN=1 WATCH_LIMIT=20 python3 steam_collect.py
DRY_RUN=1 python3 steam_signals.py
DRY_RUN=1 python3 send_brief.py
```

## 설계 메모

**감시 목록은 상위 100개만이 아니다.** 신작·출시예정과 전에 본 게임을 전부 포함한다.
상위 100은 이미 큰 게임들이라, 1인 개발자가 배울 게 있는 작은 게임은 거기 없다.
그리고 어제 보던 게임이 오늘 100위 밖으로 밀려나도 숫자를 계속 받아야 하락이 보인다.

**노이즈 바닥이 필요하다.** 8명이 80명 되면 +900%인데 아무 의미가 없다.

**급등과 상승은 겹치지 않는다.** 며칠 오르다 오늘 크게 뛴 게임은 '급등'으로만 센다.

**숫자는 "무엇이" 떴는지만 말한다.** "왜"는 검색해야 안다 — 출시, 할인, 업데이트,
스트리머 방송. 그래서 브리프 단계에 웹 검색이 열려 있다.

**게임 메타데이터는 한 번만 조회한다.** `data/games.json`에 쌓아두고 재사용한다.
매일 220개를 다시 조회하면 Steam 스토어 API가 막는다.
