# 베이스라인 — 이미지 전송 최적화 (2026-08-19) · 원본 전사

> **이 문서가 무엇인가.** 2026-08-19 이미지 전송 최적화 작업의 **원 측정 문서 전사본**이다. 요약이 아니라 전문 이전이다 — 측정 조건표·전후 대조표·함정 설명·재측정 절차·"배포 후 측정 결과" 절까지 원본에 있던 것을 전부 옮겼다.
>
> **원본 위치:** 옵시디언 볼트 `archived/baseline-image-delivery-2026-08-19.md` (6,628 bytes, mtime 2026-08-19 12:43). 원본은 그대로 남아 있다.
>
> **왜 옮겼나.** 리포 `tasks/`에 있던 사본이 사라졌고, `tasks/`·`scripts/`는 `.gitignore` 1·2번 줄에서 **루트째 제외**돼 있어 거기 둔 문서는 애초에 추적되지 않는다. 그래서 무시 규칙에 걸리지 않는 **추적되는 경로 `apps/web/perf/`** 로 옮겼다(SEC-11). `.gitignore` 안에도 *"실제로 예전에 /tmp 에 뒀다가 베이스라인 원본을 잃은 적이 있다"* 는 기록이 남아 있다 — **같은 사고를 두 번 겪지 않기 위한 이전이다.** 이 수치들은 이력서·포트폴리오 등 15곳이 인용한다.

---

## ⚠️ 이 값들은 다시 잴 수 없다

**원 측정의 인프라가 존재하지 않는다.**

| | 원 측정 (2026-08-19) | 현행 (2026-09-15) |
|---|---|---|
| FE | `https://ai-character-chat-web.pages.dev/` | `https://ddona.site` (Cloudflare Pages) |
| BE | **Cloud Run**, `asia-southeast1` (싱가포르) | **GCE VM `ddona-api`**, `asia-northeast3-a` (서울), `https://api.ddona.site` |
| DB / 캐시 | Neon · Upstash | VM 컨테이너 PostgreSQL 18 · Redis 8 |

> Cloud Run · Neon · Upstash 시절 인프라는 **2026-09-02에 삭제됐다**(`DEPLOY.md:2-4`). 옛 서술은 git 이력에만 있다.

**리전 이전만으로 TTFB(원 측정 59~67ms)와 LCP가 달라진다.** 따라서:

- **"전"(최적화 이전) 값은 영구히 재현 불가**다. 이 문서의 수치를 근거로 세우고, 다시 재려 하지 마라.
- 현행에서 잴 수 있는 것은 **"후" 값 하나뿐**이고, 그것도 원 측정과 **인프라가 달라 직접 비교가 아니다**. 인용할 때 그 사실을 함께 적어라.

## A/B 대조의 기준 커밋

**"전" 기준 커밋: `e789818`** — `chore: 채팅 품질 실험 대화록을 아카이브로 보존한다` (2026-08-18 19:58:04 +0900).

최적화는 **머지 커밋 없이 직선으로 진입**했다 — `e789818..9c7afe0` = **15커밋, 머지 0건**(`git rev-list --merges --count e789818..9c7afe0` → 0).

```
6fd4457 2026-08-18 20:06:26 feat: US-001 - AssetPurpose에 content-thumbnail 추가
3854d08 2026-08-18 20:10:01 feat: US-002 - 썸네일 생성 유틸과 키 파생 규칙 추가
028ae1c 2026-08-18 20:14:27 feat: US-003 - 업로드 완료 시 서버가 실제 파일 크기를 검증
9a932b3 2026-08-18 20:18:17 feat: US-004 - 사용자 업로드 완료 시 썸네일 생성
a51df5f 2026-08-18 20:22:23 feat: US-005 - AI 생성 이미지에 썸네일 생성
cbedf97 2026-08-18 20:26:08 feat: US-006 - 상황별 이미지 블러본에 썸네일 생성
f9ca3d0 2026-08-18 20:33:26 feat: US-007 - 기존 자산 썸네일 백필 스크립트
6555f52 2026-08-18 20:38:05 feat: US-008 - content/router.py의 목록 응답 6곳이 썸네일을 서명
05c1979 2026-08-18 20:42:04 feat: US-009 - 스튜디오 갤러리와 이미지 보관함이 썸네일을 서명
79b8559 2026-08-19 00:45:01 feat: US-010 - FE 이미지 리사이즈 유틸 추가
27720af 2026-08-19 00:48:23 feat: US-011 - uploadAsset에 리사이즈와 용량 검증 배선
34a91b7 2026-08-19 00:59:23 feat: US-012 - 업로드 진입점 3곳에 형식 제한과 purpose 전환 적용
b0c058c 2026-08-19 01:10:22 feat: US-013 - lazy loading과 첫 화면 우선 로딩 적용
6ba314a 2026-08-19 01:34:03 feat: US-014 - 채팅 말풍선 이미지 CLS 방지
9c7afe0 2026-08-19 11:56:07 fix: US-014 채팅 이미지 웰을 3:4로 바꿔 세로 이미지 축소를 되돌린다
```

"후" 측정은 `main` @ `9c7afe0` 배포본에서 잤다.

---
---

# ▼ 여기부터 원본 전문 (옵시디언 볼트 `archived/baseline-image-delivery-2026-08-19.md`)

# 베이스라인 측정 — 이미지 전송 최적화 (배포 전)

측정 시각: 2026-08-19
대상: `https://ai-character-chat-web.pages.dev/` (홈, 비로그인)
배포 상태: **`ralph/image-delivery-optimization` 미병합·미배포.** 운영 R2에는 썸네일 45건이 이미 백필돼 있으나, 서빙 코드가 옛 버전이라 여전히 원본을 서명해 내려준다 → 이 수치가 정확히 "이전" 상태다.

## 측정 조건 (배포 후 재측정 시 반드시 동일하게)

| 항목 | 값 |
|---|---|
| 뷰포트 | 390 × 844, DPR 3, mobile + touch |
| CPU | 4× 스로틀 |
| 네트워크 | Slow 4G |
| API 워밍업 | 측정 전 `GET /contents?type=story` 3회 (콜드스타트 배제, 0.45s 안정 확인) |
| 캐시 | presigned URL이라 매 실행이 자동으로 콜드 캐시 — 별도 초기화 불필요 |

## 결정적 지표 (노이즈 없음 — 이쪽이 주지표)

| 지표 | 값 |
|---|---|
| **초기 이미지 요청 수** | **20건** |
| **초기 이미지 전송량** | **21.07 MB** |
| 기타(JS·CSS·API) 전송량 | 0.25 MB |
| 전체 전송량 | 21.32 MB |
| `loading="lazy"` 적용 이미지 | **0 / 20건** |
| 이미지 1건 최대 | 1,458 KB |
| 원본 해상도 → 렌더 크기 | **768×1024 → 139×139 CSS px** |

DPR 3에서 139 CSS px면 417 물리 픽셀이면 충분한데 768을 보내고 있다.

## Core Web Vitals

| 지표 | 값 | 비고 |
|---|---|---|
| **LCP (실측, 최종)** | **36,784 ms** | LCP 요소 = `IMG.size-full object-cover` (카드 썸네일), size 19321 |
| LCP (트레이스 autoStop) | 3,584 ms (중앙값) | 3회: 3593 / 3548 / 3584, 편차 45ms |
| CLS | 0.10 | 3회 모두 동일 |
| TTFB | 59~67 ms | |
| 25초 경과 시 로드된 이미지 | **6 / 20건** | |

### ⚠️ 두 LCP 값이 다른 이유 — 재측정 시 반드시 같은 방법을 쓸 것

- **트레이스(`performance_start_trace` + `autoStop`)의 3,584ms는 진짜 LCP가 아니다.** autoStop이 이미지가 다 도착하기 전에 트레이스를 끊어서, 그 시점의 최대 요소인 **텍스트**(`P.truncate text-sm font-semibold`, 카드 제목, size 2286)를 LCP로 잡는다.
- 페이지를 끝까지 두면 카드 이미지(size 19321)가 텍스트를 추월해 **LCP가 36,784ms로 확정**된다. 실사용자가 겪는 값은 이쪽이다.
- 따라서 배포 후 비교는 **`PerformanceObserver({type:'largest-contentful-paint', buffered:true})`를 initScript로 심고 25초 이상 기다린 뒤 읽는 방식**으로 해야 한다. 트레이스 요약값만 비교하면 개선이 없는 것처럼 보인다.
- **LCP 요소가 무엇이었는지도 함께 기록할 것.** 이전=IMG였다가 이후=P(텍스트)로 바뀌면, 그건 "이미지가 더 이상 병목이 아니게 됐다"는 뜻이지 측정 오류가 아니다.

## 배포 후 기대치

| 지표 | 이전 | 예상 |
|---|---|---|
| 초기 이미지 요청 수 | 20건 | **4건** (lazy + index<4 eager) |
| 초기 이미지 전송량 | 21.07 MB | **< 1 MB** (512px WebP, 장당 ~20KB) |
| LCP | 36.8 s | 대폭 단축 — LCP 요소가 텍스트로 바뀔 가능성 높음 |
| CLS | 0.10 | 동일하거나 소폭 개선 (US-014는 채팅 화면이라 홈에는 영향 없음) |

## 재측정 절차

> ⚠️ 아래 절차의 **URL·엔드포인트는 삭제된 인프라**다. 현행 절차는 이 문서의 「현행 재측정 절차」 절을 쓴다. 원본 보존을 위해 그대로 남긴다.

```bash
# 1) API 워밍업
for i in 1 2 3; do curl -s -o /dev/null \
  https://ai-character-chat-api-612311629427.asia-southeast1.run.app/contents?type=story; done

# 2) 결정적 지표 — agent-browser HAR
agent-browser open https://ai-character-chat-web.pages.dev/
agent-browser set viewport 390 844
agent-browser network har start
agent-browser open https://ai-character-chat-web.pages.dev/
agent-browser wait --load networkidle
agent-browser network har stop /tmp/after-mobile.har
# HAR에서 image/* + r2.cloudflarestorage 요청의 건수·바이트 합산

# 3) LCP — chrome-devtools MCP
#    emulate: 390x844x3,mobile,touch / CPU 4x / Slow 4G
#    navigate_page 에 initScript 로 LCP PerformanceObserver 주입
#    25초 대기 후 window.__lcp 읽기 (ms, tag, cls, src)
```

---

# 배포 후 측정 결과 (2026-08-19, 동일 조건)

배포: `main` @ `9c7afe0` — Cloud Build `353c48fd` SUCCESS(3분 30초), Cloud Run 리비전 `ai-character-chat-api-00019-mts` 트래픽 100%, Pages 번들 `index-DJ-O7-ax.js`(새 코드 마커 5종 확인).

| 지표 | 이전 | 이후 | 변화 |
|---|---|---|---|
| **초기 이미지 전송량** | 21.07 MB | **0.27 MB** | **77배 감소 (1.3%)** |
| 초기 이미지 요청 수 | 20건 | 16건 | −4건 |
| 이미지 1건 최대 | 1,458 KB | **28 KB** | 52배 감소 |
| 썸네일(`_thumb.webp`) 비율 | 0 / 20 | **16 / 16** | 전량 전환 |
| 원본 해상도 | 768×1024 | **384×512** | |
| `loading="lazy"` 적용 | 0건 | **16건** | |
| **LCP (PerformanceObserver, 25초)** | **36,784 ms** | **6,208 ms** | **−30.6초 (83% 단축)** |
| LCP 요소 | `IMG` 원본 PNG | `IMG` `_thumb.webp` | 동일 유형 |
| 25초 시점 로드 완료 | 6 / 20건 | 16 / 16건 | |

목록 API 검증: `GET /contents?type=story` 응답 20건 전부 `_thumb.webp`를 서명.

## 예상과 달랐던 두 가지

1. **이미지 요청이 4건이 아니라 16건이다.** Chrome의 lazy 임계값이 뷰포트 바로 밖이 아니라 **약 1,250px 아래까지** 넉넉해서, 844px 뷰포트에서는 대부분의 카드가 임계 안에 들어와 미리 로드된다. `loading="lazy"`는 16건 전부에 정상 적용돼 있다(속성 확인). 전송량이 77배 줄어 실질 손해는 없지만, "첫 화면 4건"이라는 기대치는 브라우저 정책상 달성되지 않는다.
2. **LCP 요소가 여전히 IMG다.** 텍스트로 바뀔 거라 예상했지만 썸네일(19321 px²)이 여전히 카드 제목(2286 px²)보다 커서 LCP 요소로 남았다. 다만 그 이미지가 1.2MB → 22KB가 되어 36.8초 → 6.2초로 줄었다.

## 남은 개선 여지

LCP 6.2초는 여전히 "Good"(2.5s) 밖이다. 이제 병목은 이미지 크기가 아니라 **CSR SPA의 직렬 체인**(JS 번들 → React 마운트 → API 왕복 → 이미지 요청)이다. 트레이스가 지적한 `ModernHTTP`(LCP 2,930ms 절감 예상, R2 직결이 HTTP/1.1)와 `RenderBlocking`(610ms)이 다음 후보다.

---

## 참고 — 트레이스가 지적한 다른 항목 (이번 범위 밖)

- `ModernHTTP`: LCP 절감 예상 2,930ms — R2 직결 엔드포인트가 HTTP/1.1로 응답. CDN 커스텀 도메인 전환 시 함께 해소될 항목.
- `RenderBlocking`: FCP/LCP 각 ~610ms — 렌더 블로킹 리소스. SPA 번들 분할 이슈로 별개 축.
- CrUX 실사용자 데이터 없음 — 트래픽이 임계치 미만.

# ▲ 원본 전문 끝

---
---

## 별개 측정 — 채팅 말풍선 CLS 0.0818 (US-014)

> ⚠️ **위 베이스라인은 홈 화면 전용이다. 이 CLS 수치는 그 베이스라인에 없다 — 측정 대상도 조건도 다른 별개 측정이다.** 두 수치를 같은 표에 넣지 마라.

| 항목 | 홈 베이스라인 | 채팅 CLS 측정 |
|---|---|---|
| 대상 | `https://ai-character-chat-web.pages.dev/` 홈 (운영 배포본) | 로컬 `vite :5174` 의 **`/ui-demo`** 임시 섹션 (API 불필요) |
| 네트워크 | **Slow 4G** | **Slow 3G** |
| 측정 대상 | 카드 그리드 이미지 전송량·LCP·CLS | `MessageBubble` 인라인 이미지의 레이아웃 시프트 |
| 측정 도구 | HAR + `largest-contentful-paint` PerformanceObserver | `PerformanceObserver('layout-shift')` + 마커 엘리먼트 y 샘플링 |

**1차 근거:** `scripts/ralph/archive/2026-08-19-image-delivery-optimization/progress.txt:207,211` — **`/scripts/`는 `.gitignore` 1번 줄이라 이것도 추적되지 않는다.** 그래서 여기 옮긴다.

**하네스:** `/ui-demo`에 임시 MessageBubble 섹션(세로/가로 PNG 2장 + 마지막에 마커 div)을 추가하고 `public/`에 무거운 테스트 PNG 2장을 두고 Slow 3G로 스로틀. 검증 후 데모 섹션 원복 + PNG 삭제(커밋엔 `MessageBubble.tsx`/`CLAUDE.md`만 들어갔다).

**before/after 대조** (같은 페이지·같은 스로틀·`PerformanceObserver('layout-shift')`):

| | 구버전 (`max-h-80 max-w-[75%]`) | 신버전 (고정 비율 웰) |
|---|---|---|
| **CLS** | **0.0818** | **0** |
| 이미지 아래 마커 y | 999 → 1319 → 1510 (**총 511px 밀림**) | **1639 고정** (이미지 0장→2장 로드 내내 불변) |

신버전 구현: `<div className="aspect-square w-3/4 max-w-80 overflow-hidden rounded-lg bg-muted">` + `<img className="size-full object-contain">`. `ContentCard`의 썸네일 웰(`DESIGN.md` §Cards "Thumbnail well: aspect-square rounded-lg bg-muted")과 같은 패턴이고 `max-w-80`은 기존 `max-h-80`의 최대 크기를 그대로 옮긴 값이다. (이후 `9c7afe0`에서 웰을 3:4로 바꿔 세로 이미지 축소를 되돌렸다.)

**시각 크기 회귀**(`6ba314a` 시점): 세로(768×1024) 이미지는 240×320으로 **이전과 픽셀까지 동일**, 가로(1600×900)만 339×191 → 320×180으로 소폭 작아진다. 대신 비율이 어긋나는 만큼 `bg-muted` 레터박스 여백이 생긴다(크롭 없음 유지).

**웰 배경 실측:** 다크 `oklch(0.21 0 0)`(= `--muted`, 순백 아님 — DESIGN.md 밝기 천장 준수), 라이트 `oklch(0.97 0 0)`.

**이 값은 이번에 다시 재지 않는다** — 채팅 화면은 로그인이 필요해 tailscale 오리진 제약이 붙고, 측정 조건(Slow 3G, `/ui-demo`)이 홈 베이스라인과 다르다.

---

## 쓰면 안 되는 값 / 값이 낡은 것

인용 전에 반드시 이 절을 읽어라.

### ❌ `"20건 → 4건"` — PRD 목표치이고 실제가 아니다

실제는 **20건 → 16건**이다. 원본 L101이 그대로 확인해 준다: Chrome의 lazy 임계값이 뷰포트 바로 밖이 아니라 **약 1,250px 아래까지** 넉넉해서, 844px 뷰포트에서는 대부분의 카드가 임계 안에 들어와 미리 로드된다. `loading="lazy"`는 16건 전부에 정상 적용돼 있다.

**"첫 화면 4건"은 브라우저 정책상 달성되지 않는 목표치다.** 전송량이 77배 줄어 실질 손해는 없지만, 요청 수 감소를 성과로 인용하면 틀린다 — 인용할 값은 **전송량 21.07 MB → 0.27 MB**다.

### ⚠️ `"139 CSS 픽셀"` — 출처는 있으나 값이 낡았다

**"출처 없음"이 아니다.** 원본 **L27**에 `768×1024 → 139×139 CSS px`이 있고 **L29**에 근거("DPR 3에서 139 CSS px면 417 물리 픽셀이면 충분한데 768을 보내고 있다")까지 있다. 2026-08-19 시점에는 맞는 수치다.

**다만 지금 재면 139가 안 나온다.** 2026-09-11 카드그리드 개편으로 `portrait` 사다리가 2열 → **3열**이 되면서(`square` 2/3/4 · `portrait` 3/4/5 · 섞인 목록 2/3/4) 390px에서 카드 폭이 **111.33px**가 됐다(`DESIGN.md` §Cards). 현행 화면을 설명하며 139를 쓰면 틀린다.

### ❌ 원본 L83의 배포 기록 — 지금 존재하지 않는 인프라다

- Cloud Build `353c48fd`
- Cloud Run 리비전 `ai-character-chat-api-00019-mts`
- Cloud Run 엔드포인트 `...asia-southeast1.run.app`
- Cloudflare Pages 주소 `ai-character-chat-web.pages.dev`

앞의 셋은 **2026-09-02에 삭제**됐다(`DEPLOY.md:2-4`). Pages 옛 주소는 아직 살아 있으나 web Worker가 301로 `ddona.site`에 넘긴다(`apps/web/worker/legacyRedirect.ts`). **배포 기록으로 인용하지 말고, 이 측정이 어떤 빌드에서 났는지를 남기는 역사 기록으로만 읽어라.**

### ⚠️ TTFB 59~67ms · LCP 36,784ms / 6,208ms — 리전이 다르다

원 측정은 BE가 **싱가포르**(Cloud Run `asia-southeast1`)였고 현행은 **서울**(GCE VM `asia-northeast3-a`)이다. 리전 이전만으로 TTFB와 LCP가 달라진다 — 현행 실측과 나란히 놓고 "개선/악화"라고 읽지 마라. **인프라가 바뀐 두 점 사이의 차이는 코드 변경의 효과가 아니다.**

### ⚠️ LCP 3,584ms — 이건 LCP가 아니다

트레이스 autoStop이 잡은 값이고, 그 시점의 최대 요소는 **텍스트**(카드 제목)다. 진짜 LCP는 36,784ms다. 자세한 것은 위 「두 LCP 값이 다른 이유」 절.

---

## 현행 재측정 절차

> 원 측정과 **같은 조건**을 유지한다. 인프라가 달라 "전/후 비교"는 성립하지 않지만, 조건이 다르면 그나마의 참조값도 잃는다.

**대상:** `https://ddona.site` 홈.

**로그인 불필요.** `apps/web/src/routes/index.tsx`는 `beforeLoad`도 `requireSession`도 없는 공개 라우트이고, 원 측정도 비로그인이었다. → **tailscale 오리진 제약(브라우저 실검증 절차)은 적용되지 않는다.**

| 항목 | 값 |
|---|---|
| 뷰포트 | 390 × 844, DPR 3, **mobile + touch** |
| CPU | 4× 스로틀 |
| 네트워크 | **Slow 4G** (Slow 3G 아님 — 그건 채팅 CLS 측정 조건이다) |
| API 워밍업 | 측정 전 `GET https://api.ddona.site/contents?type=story` **3회** (콜드스타트 배제) |
| 캐시 | presigned URL이라 매 실행이 자동으로 콜드 캐시 — 별도 초기화 불필요 |

```bash
# 1) API 워밍업 (3회)
for i in 1 2 3; do curl -s -o /dev/null \
  "https://api.ddona.site/contents?type=story"; done

# 2) 결정적 지표(요청 수·전송량) — agent-browser HAR
agent-browser open https://ddona.site/
agent-browser set viewport 390 844
agent-browser network har start
agent-browser open https://ddona.site/
agent-browser wait --load networkidle
agent-browser network har stop <워크스페이스 안 경로>/after-mobile.har
# HAR에서 image/* + r2.cloudflarestorage 요청의 건수·바이트 합산

# 3) LCP — chrome-devtools MCP
#    emulate: 390x844x3, mobile, touch / CPU 4x / Slow 4G
#    navigate_page 에 initScript 로 LCP PerformanceObserver 주입
#    25초 이상 대기 후 window.__lcp 읽기 (ms, tag, cls, src)
```

### 함정 ① 트레이스 자동 종료의 LCP를 쓰면 안 된다

`performance_start_trace` + `autoStop`이 내놓는 값은 **진짜 LCP가 아니다**(당시 3,584ms — LCP 요소가 이미지가 아니라 **텍스트**였다). autoStop이 이미지가 다 도착하기 전에 트레이스를 끊기 때문이다.

→ **`PerformanceObserver({type:'largest-contentful-paint', buffered:true})`를 initScript로 심고 25초 이상 기다린 뒤 읽어라.** 트레이스 요약값만 비교하면 개선이 없는 것처럼 보인다.

→ **LCP 요소가 무엇이었는지(tag·src·size)도 함께 기록하라.** 이전=IMG였다가 이후=P(텍스트)로 바뀌면 그건 "이미지가 더 이상 병목이 아니게 됐다"는 뜻이지 측정 오류가 아니다.

### 함정 ② CLS는 시프트가 뷰포트 밖이면 0으로 나온다

`layout-shift` 엔트리만 믿으면 안 된다 — 시프트가 뷰포트 **밖**에서 일어나면 값이 0으로 나온다(US-014 첫 측정에서 구버전도 0이 나왔다). 확실한 방법은 둘이고 **둘 다 하는 게 제일 좋다**:

1. 문제 구간을 `scrollIntoView`로 뷰포트에 올린 뒤 관찰한다.
2. 아래에 마커 엘리먼트를 두고 `getBoundingClientRect().top + scrollY`를 rAF로 샘플링해 **직접 이동량을 본다**(US-014의 511px가 이렇게 나온 값이다).

### 기타 하네스 함정 (원 측정 런에서 밟은 것)

- **CDP `resize_page`로 390px를 줘도 실제 뷰포트는 500px까지만 좁아진다**(창 최소 폭). 모바일 열 수를 검증할 땐 `innerWidth`를 실제로 읽어 확인하라.
- chrome-devtools MCP의 `take_screenshot --filePath`는 `upload_file`과 마찬가지로 **워크스페이스 루트 밖(`/tmp`)을 거부한다** → 워크트리 안에 저장하고 지울 것.
- 브라우저에서 테마를 바꿔 확인했다면 `localStorage.removeItem("theme")`으로 되돌릴 것 — 이 localStorage는 **포트가 달라도 localhost 전체가 공유**해서 사용자의 dev 브라우저 상태가 라이트로 남는다.

---

## 2026-09 현행 실측

**미측정.**

위 「현행 재측정 절차」를 그대로 실행한 결과를 여기 적는다. 기록할 값: 초기 이미지 요청 수 · 초기 이미지 전송량 · 이미지 1건 최대 · 썸네일 비율 · LCP(PerformanceObserver, 25초) · **LCP 요소(tag/src/size)** · CLS · TTFB · 측정 시각 · FE 번들 해시.

> 기록할 때 **인프라가 다르다는 주석을 반드시 함께 남겨라**(서울 GCE VM vs 싱가포르 Cloud Run). 이 값은 2026-08-19 수치와 **직접 비교 대상이 아니다.**
