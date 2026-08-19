---
name: AI 캐릭터 챗 서비스
description: 내가 만든 AI 캐릭터·스토리로 롤플레이 대화를 나누는 오픈 플랫폼
colors:
  background: "oklch(0.160 0.000 0)"
  foreground: "oklch(0.930 0.000 0)"
  card: "oklch(0.210 0.000 0)"
  card-foreground: "oklch(0.930 0.000 0)"
  popover: "oklch(0.210 0.000 0)"
  popover-foreground: "oklch(0.930 0.000 0)"
  primary: "oklch(0.720 0.180 0)"
  primary-foreground: "oklch(0.160 0.000 0)"
  secondary: "oklch(0.260 0.000 0)"
  secondary-foreground: "oklch(0.930 0.000 0)"
  muted: "oklch(0.210 0.000 0)"
  muted-foreground: "oklch(0.680 0.000 0)"
  accent: "oklch(0.260 0.000 0)"
  accent-foreground: "oklch(0.930 0.000 0)"
  destructive: "oklch(0.640 0.190 25)"
  destructive-foreground: "oklch(0.160 0.000 0)"
  border: "oklch(0.300 0.000 0)"
  input: "oklch(0.300 0.000 0)"
  ring: "oklch(0.720 0.180 0)"
typography:
  display:
    fontFamily: "Pretendard Variable, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: "2rem"
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Pretendard Variable, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: "1.75rem"
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Pretendard Variable, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
    letterSpacing: "normal"
  label:
    fontFamily: "Pretendard Variable, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: "1rem"
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "14px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  2xl: "24px"
  3xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    height: "32px"
    padding: "0 10px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "oklch(0.720 0.180 0 / 0.8)"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "32px"
    padding: "0 10px"
  button-outline-hover:
    backgroundColor: "{colors.muted}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "32px"
    padding: "0 10px"
  button-ghost-hover:
    backgroundColor: "{colors.muted}"
  button-destructive:
    backgroundColor: "oklch(0.640 0.190 25 / 0.1)"
    textColor: "{colors.destructive}"
    rounded: "{rounded.lg}"
    height: "32px"
    padding: "0 10px"
  button-destructive-hover:
    backgroundColor: "oklch(0.640 0.190 25 / 0.2)"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    rounded: "{rounded.xl}"
    padding: "12px"
  input:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "32px"
    padding: "0 12px"
  badge-status:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  badge-restricted:
    backgroundColor: "oklch(0.640 0.190 25 / 0.1)"
    textColor: "{colors.destructive}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  dialog:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.popover-foreground}"
    rounded: "{rounded.xl}"
    padding: "24px"
---

# Design System: AI 캐릭터 챗 서비스

## 1. Overview

**Creative North Star: "불 꺼진 방의 유일한 빛(The Only Light in the Room)"**

늦은 밤, 불을 끄고 침대에 누워 혼자 캐릭터와 대화하는 장면. 이 한 장면이 이 시스템의 모든 결정을 강제한다. 방의 조명은 꺼져 있고 **화면이 그 방의 유일한 광원이다**. 사용자의 눈은 이미 어둠에 적응해 있고, 손은 하나뿐이며, 급할 것이 없고, 옆에는 아무도 없다. 그래서 이 인터페이스는 인쇄된 종이가 아니라 **빛을 내뿜는 물건**으로 설계된다 — 밝기는 스타일이 아니라 예산이고, 모든 밝은 표면은 그 예산을 쓴다.

여기서 다크는 선호가 아니라 **기본 조건**이다(`apps/web`는 저장값이 없으면 다크로 부팅한다). 배경이 순수 검정(oklch 0)이 아닌 near-black(0.160)인 것도, 본문이 순백(oklch 1)이 아닌 소프트 화이트(0.930)인 것도 취향이 아니다 — 순수 검정 위의 밝은 텍스트는 OLED에서 번지고 레이어 위계를 쌓을 여지를 남기지 않으며, 어두운 방에서의 순백은 그냥 눈부심이다. 라이트 팔레트는 다크의 열등한 형제가 아니라 **다른 장면**을 위한 것이다: 낮의 사용자, 그리고 항상 라이트로 고정된 관리자 앱(`apps/admin`).

몰입은 시끄러움이 아니라 고요함에서 나온다. 표면(배경·카드·보더 사다리)이 끝까지 무채색인 이유가 이것이다 — 색을 가질 수 있는 것은 사용자가 만든 썸네일, 지금 누를 수 있는 한 곳(`primary`), 그리고 위험(`destructive`)뿐이다. 그래서 그 한 장과 그 한 버튼이 유일하게 빛난다. 명시적으로 지양하는 것: 자극적이거나 성인 지향적인 비주얼 톤(전연령 정책), 그리고 어두운 방에서 사용자를 놀라게 하는 모든 것 — 갑작스러운 움직임, 큰 밝은 면적, 예고 없는 대비 점프.

**Key Characteristics:**
- 다크가 기본값(web), 라이트는 낮·admin용 대등한 대안 — 두 팔레트 모두 **표면은 chroma 0**이다
- 다크에서 가장 밝은 값은 `foreground`(0.930)이며 그보다 밝은 것은 존재하지 않는다
- `primary`는 **핑크-레드 강조**이자 이 시스템의 유일한 유채색 솔리드 채움이다(라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`, `ring`도 같은 값)
- 그 밖의 유채색은 위험 액션(`destructive`, 항상 `/10` 틴트)과 사용자가 고른 스탯 스와치뿐 — 배경·카드·보더 사다리는 무채색을 유지한다
- 정지 상태는 평평하다 — 그림자는 앱 전체에 5개뿐이고 그중 3개가 떠 있는 팝오버다
- 크롬은 sticky 헤더 하나(`h-14`)뿐 — 하단 탭바도, 사이드 레일도, 푸터도 없다

## 2. Colors

**표면은 명도 하나로만 위계를 만들고(무채색 사다리), 색은 강조 지점에만 얹는다.** 레이어 구분은 여전히 색상(hue)이 아니라 밝기 차이로만 하고, 유채색은 `primary`/`ring`·`destructive`·사용자 콘텐츠 셋에만 남긴다. 프론트매터는 **기본 테마인 다크**를 담는다. 두 팔레트 모두 `packages/ui/src/styles/globals.css` 한 곳에서만 정의된다.

아래 본문의 oklch 값은 `globals.css`와 **문자열까지 같게** 적는다(프론트매터 블록만 도구 규약상 3자리 정규화 표기 — 같은 값이다). 문서와 코드가 어긋났는지는 grep 한 번으로 확인할 수 있어야 한다.

### Primary
- **Pink-Red Accent (핑크-레드 강조)** — `primary`(= `ring`, 라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`): 주요 CTA(플레이, 발행/제출), 사용자 말풍선, 포커스 링·보더, 활성 토글, 체크박스·스위치의 on 상태. **이 시스템에서 유일한 유채색 솔리드 채움이다** — `destructive`가 언제나 `/10` 틴트인 것과 형태로 갈린다.
- **채움 위 텍스트는 항상 `primary-foreground`로 뒤집는다**(라이트 `oklch(1 0 0)` / 다크 `oklch(0.16 0 0)`): 라이트 **6.70:1** / 다크 **7.18:1**. 라이트 채움이 더 어두운 것은 그 위에 흰 텍스트를 얹기 때문이다.
- **명도는 hover까지 보고 고른 값이다** — `bg-primary/80`(hover)에서도 `background` 위 라이트 **4.77:1** / 다크 **4.90:1**로 AA를 유지한다. 정지 대비만 재고 토큰을 바꾸면 hover에서 깨진다.
- **`text-primary`의 대비 대역은 5.78~7.18:1**이다(background / card / popover / secondary·accent 전부 AA 이상, 최저는 라이트에서 `bg-secondary/50` 위 5.78). `primary`가 `foreground`와 같은 값이던 시절의 15.8:1이 아니므로, 새 표면 위에 `text-primary`를 얹을 땐 이 대역을 하한으로 본다.
- **`destructive`와의 거리**: hue를 0 대 25로 **25° 벌렸고** Oklab ΔE 라이트 0.096 / 다크 0.114 — JND(~0.02)의 5배다. chroma는 sRGB 게멋 상한(hue 0에서 L 0.5 → 0.203, L 0.72 → 0.191)에 걸려 더 벌릴 여지가 없어 hue와 명도로만 가른다.
- **Hover**: 별도 토큰 없이 `bg-primary/80`(투명도)으로 만든다.

### Neutral
다크와 라이트는 같은 사다리를 뒤집은 구조다. **다크에서는 위로 뜰수록 밝아지고, 라이트에서는 위로 뜰수록 어두워진다.**

| 역할 | 다크 | 라이트 | 쓰임 |
|---|---|---|---|
| `background` | oklch(0.160) | oklch(1.000) | 기본 배경 |
| `card` / `popover` / `muted` | oklch(0.210) | oklch(0.970) | 배경 위 첫 레이어 — 카드, 팝오버, 썸네일 우물 |
| `secondary` / `accent` | oklch(0.260) | oklch(0.930) | 두 번째 레이어 — hover/선택 배경, 배지, 필터 칩 |
| `border` / `input` | oklch(0.300) | oklch(0.890) | 구분선, 인풋 테두리 |
| `muted-foreground` | oklch(0.680) | oklch(0.530) | 보조 텍스트 — 캡션, 타임스탬프, 조회수 |
| `foreground` | oklch(0.930) | oklch(0.220) | 본문 텍스트 |

측정된 대비(WCAG 2.x, sRGB 변환 기준):
- 다크 `foreground` on `background`: **15.79:1** / 라이트 `foreground` on `background`: **17.31:1**
- 다크 `muted-foreground` on `background`: **6.74:1**, on `secondary`: **5.39:1** — 두 레이어 모두 AA 통과
- 라이트 `muted-foreground` on `background`: **5.28:1**, on `card`: **4.84:1** — 통과. 단 **on `accent`(0.930)에서는 4.30:1로 AA 미달**이므로, 라이트에서 `accent` 표면 위에 `muted-foreground`로 본문을 올리지 않는다(배지처럼 큰 텍스트가 아닌 이상).

### Semantic
- **Destructive (경고 레드)** — 다크 oklch(0.640 0.190 25) / 라이트 oklch(0.550 0.190 25): 삭제/탈퇴/거부/이용제한. `primary`와 함께 시스템 유채색 둘 중 하나이며, 둘은 hue(25 대 0)와 **형태**로 갈린다 — destructive는 언제나 틴트, primary는 솔리드 채움이다. 다크에서 빨강을 밝힌 것은 텍스트 대비를 위해서이며(on `background` **5.27:1**), 그 대가로 **밝힌 빨강 위 흰 텍스트는 3.68:1로 AA에 미달한다** — 그래서 `destructive-foreground`도 함께 어둡게 뒤집는다(0.160, 대비 5.27:1). 토큰을 조정할 때 이 쌍을 반드시 함께 유지할 것.
- **실제 구현에서 destructive는 채움이 아니라 틴트다**: 버튼도 배지도 `bg-destructive/10 text-destructive`를 쓴다. 어두운 방에서 솔리드 레드 블록은 그 자체로 놀람이다.

### Tertiary
- **스탯 스와치(User-chosen swatches)** — `packages/ui/src/lib/color-palette.ts`의 10색 고정 팔레트(rose/orange/amber/lime/emerald/teal/sky/indigo/violet/fuchsia, 예: oklch(0.62 0.19 350)). **UI 팔레트가 아니라 사용자 데이터다** — 채팅방 스탯 게이지와 컬러 피커에서 사용자가 직접 고른 값이며, 테마에 따라 변하지 않는다. 시스템 토큰으로 승격하지 말 것.

### Named Rules
**The Brightness Budget Rule (밝기 예산 규칙).** 화면은 방의 유일한 광원이다. 다크 테마에서 `foreground`(0.930)보다 밝은 값은 **존재하지 않는다** — 순백(oklch 1.000)은 다크에서 금지다. 밝은 표면은 예산이며, 큰 면적일수록 비싸다. `primary` 채움이 `h-8`(32px) 버튼 크기에 머무는 것은 우연이 아니다. 핑크-레드로 바뀐 뒤에도 다크 `primary`의 L(0.72)은 이 천장 아래에 있다.

**The Inverted Ladder Rule (반전 사다리 규칙).** 다크에서는 위로 뜨는 레이어일수록 밝아진다(0.160 → 0.210 → 0.260 → 0.300). 라이트에서는 정확히 반대다(1.000 → 0.970 → 0.930 → 0.890). 새 레이어를 추가할 때 이 사다리에 없는 중간값을 발명하지 말 것.

**The One-Accent Rule (강조는 하나뿐 규칙).** 색이 존재할 수 있는 곳은 셋뿐이다 — 강조 지점(`primary`/`ring`), 사용자 콘텐츠(썸네일, 스탯 스와치), 위험 액션(`destructive`). 배경·카드·보더 사다리와 그 위의 텍스트·배지·비활성 컨트롤은 끝까지 무채색이다. 새 UI 색(성공 그린, 정보 블루, 브랜드 세컨더리)을 발명하지 말 것 — 상태는 아이콘과 텍스트로 구분한다. 그리고 강조는 **하나**라는 뜻이기도 하다: 한 화면에서 `primary`로 칠할 것을 고를 때 "지금 누를 수 있는 것"과 "지금 내가 한 말"(사용자 말풍선) 밖으로 번지면, 썸네일 한 장이 유일하게 빛난다는 전제가 무너진다.

## 3. Typography

**Display / Title / Body / Label Font:** Pretendard Variable (with `-apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif`)

`--font-heading`은 `--font-sans`의 별칭이다(`globals.css`) — 제목용 별도 서체는 존재하지 않으며, 앱 코드에서 `font-heading`은 한 번도 쓰이지 않는다.

**Character:** 한글 가독성이 검증된 단일 휴머니스트 산세리프를 굵기(weight)만 바꿔 전 화면에 쓴다. 실제로 코드에 존재하는 굵기는 셋뿐이다 — medium(500) / semibold(600) / bold(700). 크기 스케일도 `text-2xl`(1.5rem)에서 멈춘다: 이 제품에는 히어로가 없고, 가장 큰 글자도 페이지 제목이다.

### Hierarchy
- **Display** (700, 1.5rem/2rem, -0.025em): 페이지 제목(h1)과 마이페이지 섹션 제목. 화면 내 최상위.
- **Title** (600, 1.25rem/1.75rem, -0.025em): 인증 화면 제목, 모달 헤더, 카드 제목.
- **Body** (400, 0.875rem/1.25rem): 본문, 대화 메시지, 설명. 앱에서 압도적으로 가장 많이 쓰이는 크기(122회)이며 **사실상의 기본값**이다. 산문은 65-75자에서 줄바꿈.
- **Label** (500, 0.75rem/1rem): 폼 라벨, 캡션, 메타(조회수·타임스탬프), 에러 텍스트.
- **Badge** (500, 11px): 상태 배지 전용. **스케일 밖의 값이며 의도된 예외다** — `text-xs`(12px)는 배지 안에서 너무 크고, 이 한 티어를 위해 스케일을 늘리지 않았다.

### Named Rules
**The Single Family Rule (단일 서체 규칙).** 새 화면에 다른 서체 패밀리를 추가하지 않는다. 위계는 굵기·크기·자간으로만 만든다. `font-medium` / `font-semibold` / `font-bold` 셋 밖의 굵기를 도입하지 말 것.

**The No-Hero Rule (히어로 없음 규칙).** `text-2xl`(1.5rem)이 천장이다. 이 제품은 랜딩 페이지가 아니라 사용자가 이미 들어와 있는 도구다 — 큰 글자로 설득할 대상이 없다. clamp()나 vw 기반 유동 타이포는 쓰지 않는다(모든 크기는 고정 rem).

## 4. Elevation

**이 시스템은 사실상 그림자가 없다.** 깊이는 그림자가 아니라 §2의 명도 사다리(tonal layering)로 표현한다 — 다크에서 카드가 배경 위에 있다는 것은 그림자가 아니라 `card`(0.210)가 `background`(0.160)보다 밝다는 사실로 전달된다. 이것이 "불 꺼진 방"에서 옳은 선택이다: 어두운 방에서 드리운 그림자는 보이지도 않고, 보이게 만들려면 배경을 더 어둡게 깎아야 하는데 그럴 여지가 없다.

앱 전체에 그림자는 **5개뿐이며**, 그중 3개는 화면 위로 떠 있는 팝오버(단축어 자동완성, 컬러 피커, 아이콘 피커)다. 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다.

### Shadow Vocabulary
- **Floating panel** (`shadow-md` + `ring-1 ring-foreground/10`): 트리거 위에 떠서 열리는 커스텀 팝오버 전용. 그림자만으로는 다크에서 경계가 보이지 않으므로 **반드시 `ring`과 함께 쓴다** — 이 조합이 다크에서 실제로 경계를 만드는 것은 ring 쪽이다.
- **Overlay scrim** (`bg-black/10` + `backdrop-blur`): Dialog/Sheet/AlertDialog 배경. **라이트/다크 공통 하드코딩이며 의도된 것이다**(US-131 판정) — 다크에서는 블러가 배경 분리를 담당한다. 시맨틱 토큰으로 바꾸지 말 것.

### Named Rules
**The Flat-at-Rest Rule (정지 시 평평 규칙).** 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다. 그림자는 z축으로 실제로 떠 있는 엘리먼트에만 붙는다. 감사 테스트: 새 컴포넌트에 `shadow-*`를 쓰려 한다면, 그것이 클릭으로 열려서 다른 것 위에 뜨는 물건인지 자문하라. 아니라면 `border`를 쓴다.

**The Ring-Not-Shadow Rule (그림자 대신 링 규칙).** 다크에서 떠 있는 표면의 경계는 그림자가 아니라 `ring-1 ring-foreground/10`이 만든다. 그림자를 더 진하게 키워 경계를 만들려 하지 말 것 — 어두운 배경 위에서는 아무리 키워도 보이지 않는다.

## 5. Components

캐주얼하지 않고 **조용하다**. 컴포넌트는 작고(기본 높이 32px), 라운드는 부드럽지만 장식적이지 않으며, 반응은 즉각적이되 과장이 없다. 밤에 한 손으로 쓰는 물건의 성격이다.

### Buttons
- **Shape:** radius `lg`(10px), 기본 높이 `h-8`(32px). 크기 4단계(`xs` 24px / `sm` 28px / `default` 32px / `lg` 36px)와 아이콘 전용 4종.
- **Primary:** 핑크-레드 `primary` 채움 + `primary-foreground` 텍스트, hover 시 `bg-primary/80`. 다크에서는 밝힌 핑크 + 어두운 텍스트, 라이트에서는 어두운 핑크 + 흰 텍스트 — **규칙은 "채움 위 텍스트를 뒤집는다"로 동일하다**(§2 Primary).
- **Outline:** `border-border` + `background`, hover 시 `bg-muted`.
- **Secondary:** `secondary` 채움, hover는 `color-mix(in oklch, var(--secondary), var(--foreground) 5%)` — 사다리를 벗어나지 않도록 토큰에서 파생시킨다.
- **Ghost:** 투명, hover 시 `bg-muted`.
- **Destructive:** **채움이 아니라 틴트다** — `bg-destructive/10 text-destructive`, hover 시 `/20`. 솔리드 레드 버튼은 이 시스템에 존재하지 않는다.
- **Link:** `text-primary` + underline-offset-4.
- **Press feedback:** `active:translate-y-px` — 1px 눌림. 이게 이 시스템의 유일한 촉각 신호다(팝오버를 여는 버튼은 제외).
- **Focus:** `focus-visible:ring-3 ring-ring/50` + `border-ring`. 항상 노출한다.

### Toggles (선택 칩 / 목록형 선택지)
단일선택 토글은 `packages/ui/src/components/toggle.tsx`의 `toggleVariants` 하나에서만 정의된다 — 장르 필터, 헤더의 캐릭터/스토리, 테마 선택, 빌더의 시작설정·공개범위가 전부 같은 프리미티브다.

- **Shape:** 칩은 `sm`(높이 28px, radius `min(md,12px)`), 그 밖은 `default`(32px, radius `lg`). 테두리 `border-input`, 배경 투명.
- **선택 상태는 `primary` 솔리드 채움 + `primary-foreground` 텍스트**다(§2 Primary가 "활성 토글"을 primary 용처로 명시). 다크 **7.18:1** / 라이트 **6.70:1**, hover(`bg-primary/80`)에서도 **4.90:1** / **4.77:1**로 AA를 유지한다.
- **선택 상태를 `bg-muted`로 칠하지 말 것.** 상류 shadcn 기본값이지만 이 시스템에서 그 값은 `background`와 명도가 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160, 약 **1.3:1**) 선택이 보이지 않고, `hover:bg-muted`와 색이 같아 선택 안 된 항목에 마우스만 올려도 구별되지 않는다. `shadcn add toggle`로 재생성하면 이 값이 되돌아온다.
- **`variant="list"` — 넓은 행이 세로로 쌓인 목록형 선택지**(신고 사유 등)**에만 쓴다.** 이 형태에 솔리드 채움을 쓰면 같은 화면의 primary CTA와 같은 크기·같은 색 덩어리가 둘이 되어 무엇이 액션인지 흐려진다(밝기 예산 규칙 — `primary` 채움은 버튼 크기에 머문다). 그래서 `border-primary` + `text-primary` + `bg-primary/10` 틴트로만 표시하고(선택 행 텍스트 대비 **5.24:1**), 솔리드 채움은 CTA에 남긴다.
- **감사 테스트:** 토글에 새 선택 표시를 만들려 한다면, 그 항목이 버튼만 한 크기인지 자문하라. 그렇다면 기본 채움을 그대로 쓰고, 한 줄을 가득 채우는 크기라면 `list`를 쓴다.
- **호출부에 선택 상태 클래스를 직접 붙이지 말 것** — 프리미티브에 없는 규칙을 호출부마다 문자열로 붙이면 새로 추가되는 화면이 조용히 빠진다(실제로 17곳 중 2곳만 맞았던 적이 있다).

### Cards / Containers
- **Corner Style:** radius `xl`(14px).
- **Background:** `bg-card`, 테두리 `border-border` 한 줄. **그림자 없음.**
- **Internal Padding:** 12px(콘텐츠 카드) / 16px(초안 카드) / 32px(인증 카드).
- **Hover:** `hover:bg-accent/50` — 사다리 위로 반 칸.
- **Thumbnail well:** `aspect-square rounded-lg bg-muted`, 이미지 없으면 `ImageOff` 아이콘을 `text-muted-foreground`로.
- **Empty state:** `rounded-xl border border-dashed border-border py-16` — 점선은 빈 상태와 컬러 피커에만 쓴다.

### Inputs / Fields
- **Style:** radius `md`(8px), `border-input` 테두리, 투명 배경.
- **Focus:** `ring-3 ring-ring/50` — 버튼과 동일한 포커스 언어.
- **Error:** `aria-invalid`에 `border-destructive` + `ring-destructive/20`. 에러 텍스트는 Label 크기 + `text-destructive`.

### Navigation
- **크롬은 sticky 헤더 하나뿐이다.** `sticky top-0 z-30 h-14 border-b border-border bg-background`, 내부는 `mx-auto max-w-6xl px-4 sm:px-6`. 하단 탭바·사이드 레일·푸터는 **존재하지 않으며, 추가하지 않는다** — 크롬은 얇고 항상 동일해야 한다.
- **워드마크는 아이콘 없는 타이포그래픽 마크 하나다**(`또나`, `text-lg font-bold tracking-tight text-foreground`). 파비콘(Pretendard Bold `또` 글리프)·OG 이미지(`또나` 워드마크)와 같은 계보이며, 로고에 심볼 아이콘을 붙이지 않는다 — 마크가 둘이면 브랜드가 둘이다. 색도 없다: 로고는 강조 지점이 아니므로 `primary`가 아니라 `foreground`다(§2 One-Accent Rule).
- **모바일 대응은 레이아웃 분기가 아니라 라벨 숨김이다**: 토글 라벨이 `sm:` 미만에서 사라지고 아이콘만 남는다. **워드마크는 예외로 항상 노출한다** — 2자(≈36px)라 숨겨서 아낄 폭이 없고, 숨기면 홈 링크에 접근 가능한 이름이 남지 않는다. 검색은 `w-8`에서 `w-40 sm:w-64`로 펼쳐진다 — 다만 이 값은 선호 폭이지 하한이 아니다. 우측 아이콘 그룹과 펼친 검색은 `min-w-0`을 갖고 있어, 폭이 모자라면(390px에서 아이콘 4개 + 펼친 검색) 아이콘(`shrink-0`)이 아니라 검색만 줄어든다. 헤더에 아이콘을 더 추가할 땐 이 상태에서 `bar.scrollWidth === bar.clientWidth`를 실측할 것.
- **채팅 화면은 뷰포트 고정이다**: `h-[calc(100dvh-3.5rem)]`. 이 `3.5rem`은 헤더의 `h-14`를 수동으로 미러링한 값이므로 **헤더 높이를 바꾸면 5곳을 함께 고쳐야 한다.**
- **채팅 더보기 패널은 1024px 이상에서 인라인 사이드바다**(`w-72`, `border-l border-border`, `bg-card`, 채팅 헤더 아래부터 바닥까지). 이것은 사이드 레일이 아니다 — 기본이 닫힘이고 채팅 라우트에만 있으며 ⋮로 여는 일시적 패널이다(크롬은 여전히 `h-14` 헤더 하나뿐이다). 오버레이가 아니라 채팅 컬럼과 폭을 나눠 갖는 이유는 **열어둔 채로 대화를 계속 읽고 보낼 수 있어야** 하기 때문이다. 분기는 `lg:` 클래스가 아니라 JS(`useMedia`)로 한다 — `Sheet`는 body로 포털돼 부모 클래스가 닿지 않고, 열린 `Sheet`는 포커스 트랩까지 걸어 인라인 패널과 공존할 수 없다.
- **1024px 미만에서 같은 패널은 바닥에서 올라오는 드롭업이다**(`Sheet side="bottom"` + `top-[118px]` + `rounded-t-xl`). 우측 시트가 아니라 드롭업인 이유는 **누구와 대화 중인지가 계속 보여야** 하기 때문이다 — 시트 상단을 채팅 헤더 바로 아래에 붙여 아바타·캐릭터명·방 이름을 남긴다. 그 `118px`는 전역 헤더 `h-14`(56) + border 1 + 채팅 헤더 60 + border 1을 실측한 값으로, 위의 `calc(100dvh-3.5rem)`와 같은 계열의 수동 미러링이다(헤더 높이를 바꾸면 여기도 함께 고친다). 전역 헤더는 채팅 헤더 위에 있으므로 함께 남는다 — 둘을 따로 고를 수 없다. 오버레이 스크림은 그 위를 덮으므로 헤더는 보이되 흐려진다(의도된 모달 표현).

### Status badges
- **Shape:** `inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium`. 전용 `Badge` 프리미티브는 없고 각 자리에서 손으로 조립한다.
- **중립 상태(공개/링크공개/비공개):** `bg-muted text-muted-foreground`.
- **이용제한:** `bg-destructive/10 text-destructive` — 틴트, 채움 아님.
- **타입(캐릭터/스토리):** `bg-secondary text-secondary-foreground` + 14px 아이콘.
- **삭제:** 배지가 아니라 전체 패널 빈 상태로 표현한다(`ContentUnavailableState`) — 아이콘 + 제목 + 설명.
- 상태 배지는 소유자에게만 렌더한다.

### Layout containers
페이지 컨테이너의 표준 관용구는 `mx-auto flex max-w-* flex-col gap-* px-6 py-10`이다. max-width는 콘텐츠 밀도에 따라 고른다: 그리드형 목록 `max-w-5xl`, 프로필 `max-w-4xl`, 폼·빌더·상세·채팅 `max-w-2xl`. 인증 화면만 다른 셸을 쓴다(`min-h-screen items-center justify-center px-4 py-12` + `sm:max-w-sm` 카드). **인증 화면에 브랜드 마크를 따로 두지 않는다** — 전역 헤더가 모든 라우트에 마운트되므로 카드 위에 워드마크를 얹으면 같은 단어가 한 화면에 두 번 나온다(§Navigation).

**간격은 gap 하나로만 만든다** — `space-y-*`와 `divide-*`는 앱 전체에서 **0회** 사용이며, 레이아웃은 100% `flex flex-col gap-*`이다. 가장 많이 쓰이는 값은 `gap-1.5`(6px, 라벨↔인풋)와 `gap-2`(8px, 버튼 행)다.

**Tailwind 브레이크포인트는 `sm`(640px)과 `md`(768px) 둘뿐이다.** `lg:` 이상의 클래스는 앱에 존재하지 않는다 — 콘텐츠 그리드가 `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`에서 멈추는 것이 의도다. 유일한 1024px 분기는 채팅 더보기 패널(§Navigation)이고, 그것도 CSS가 아니라 JS 미디어쿼리다.

### Motion
- **모션 라이브러리는 없다.** `tw-animate-css` + Tailwind 유틸리티만 쓴다. 이 시스템에 코레오그래피는 존재하지 않는다.
- **지속시간은 100-300ms**: 팝오버 100ms, 스텝 전환·검색 확장 200ms, 스탯 게이지 300ms. `ease-out`.
- **모든 모션은 `motion-safe:` 접두사로 가드한다** — 어두운 방에서 갑작스러운 움직임은 놀람이다. 새 애니메이션을 추가할 때 `motion-safe:`를 빼먹지 말 것.
- 상태 전달만 한다: 스텝 전환, 팝오버 열림, 게이지 변화, 타이핑 인디케이터. 장식적 등장 연출은 금지.

## 6. Do's and Don'ts

### Do:
- **Do** 색을 쓰고 싶으면 그것이 강조 지점(`primary`/`ring`)인지, 사용자 콘텐츠인지, 위험 액션인지 먼저 확인한다. 셋 다 아니면 무채색이다.
- **Do** 새 표면을 §2의 명도 사다리 위에 올린다(다크 0.160/0.210/0.260/0.300). 사다리에 없는 중간값을 발명하지 않는다.
- **Do** 깊이를 그림자가 아니라 명도로 만든다. 카드가 떠 보여야 하면 `bg-card`를 쓰지 `shadow-md`를 쓰지 않는다.
- **Do** 다크에서 채움 위 텍스트를 뒤집는다 — `primary`와 `destructive` 모두 밝은 채움 + 어두운 텍스트다. 이 쌍을 깨지 말 것.
- **Do** 모든 애니메이션에 `motion-safe:`를 붙인다.
- **Do** 모든 인터랙티브 엘리먼트에 `focus-visible` 링(`ring-3 ring-ring/50`)을 유지한다(전연령/접근성 정책).
- **Do** 본문에 `text-sm`(0.875rem)을 쓴다. 이것이 기본값이다.

### Don't:
- **Don't** 다크에서 순백(`oklch(1)`, `text-white`, `#fff`)을 쓰지 않는다. 천장은 `foreground`(0.930)다.
- **Don't** 자극적이거나 성인 지향적인 비주얼 톤을 쓰지 않는다(전연령 정책) — 원색 대비, 네온, 선정적 이미지 트리트먼트.
- **Don't** `primary`를 배경 전체 채우기나 텍스트 그라디언트로 쓰지 않는다. `primary`는 "지금 누를 수 있는 것"과 "지금 내가 한 말"(사용자 말풍선)에만 쓴다.
- **Don't** 솔리드 레드 버튼/배지를 만들지 않는다. destructive는 항상 `/10` 틴트다.
- **Don't** 카드·버튼·인풋에 정지 상태 그림자를 붙이지 않는다.
- **Don't** Toast/Alert에 색상 사이드 보더를 쓰지 않는다. 상태는 아이콘 색과 텍스트로만 구분한다.
- **Don't** 서로 다른 서체 패밀리를 섞지 않는다 — Pretendard 굵기 변화로만 위계를 만든다.
- **Don't** clamp()나 vw 유동 타이포를 쓰지 않는다. 모든 크기는 고정 rem이고 천장은 `text-2xl`이다.
- **Don't** 하단 탭바·사이드 레일·푸터를 추가하지 않는다. 크롬은 `h-14` 헤더 하나다.
- **Don't** 라이트 테마에서 `accent`(0.930) 표면 위에 `muted-foreground`로 본문을 올리지 않는다 — 4.30:1로 AA 미달이다.
- **Don't** `space-y-*`나 `divide-*`를 쓰지 않는다. 간격은 `flex flex-col gap-*`으로만 만든다.
