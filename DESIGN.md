<!-- SEED -->
---
name: AI 캐릭터 챗 서비스
description: 내가 만든 AI 캐릭터·스토리로 롤플레이 대화를 나누는 오픈 플랫폼
colors:
  bg: "oklch(1.000 0.000 0)"
  surface: "oklch(0.970 0.000 0)"
  ink: "oklch(0.220 0.000 0)"
  muted: "oklch(0.530 0.000 0)"
  border: "oklch(0.890 0.000 0)"
  primary: "oklch(0.220 0.000 0)"
  primary-deep: "oklch(0.380 0.000 0)"
  accent: "oklch(0.930 0.000 0)"
  destructive: "oklch(0.550 0.190 25)"
typography:
  display:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "clamp(1.5rem, 2.5vw, 2rem)"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "10px"
  lg: "16px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.bg}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  dialog:
    backgroundColor: "{colors.bg}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: AI 캐릭터 챗 서비스

## 1. Overview

**Creative North Star: "따뜻한 저녁 채팅방(The Evening Chatroom)"**

늦은 저녁, 익숙한 캐릭터와의 대화창을 열었을 때의 느낌 — 화면은 조용하고 밝지만, 그 안에서 오가는 이야기와 캐릭터 카드만큼은 은은한 로즈 톤으로 따뜻하게 빛난다. 크롬(헤더/버튼/입력창)은 절제되고 얇게 유지해 콘텐츠(썸네일, 이름, 대화 텍스트)가 항상 주인공이 되도록 하고, 브랜드 컬러(로즈)는 CTA·포커스·활성 상태처럼 "지금 누를 수 있는 것"에만 집중 사용한다(Restrained 전략). 이는 `packages/ui`가 캐주얼한 소비자 앱(`apps/web`)과 실무형 관리자 앱(`apps/admin`) 양쪽이 공유하는 기반 레이어이기 때문이기도 하다 — 두 표면 모두에서 과하지 않게 통한다.

명시적으로 지양하는 것: 성인 지향적이거나 자극적인 원색 대비(전연령 정책), 그리고 딱딱한 기업 SaaS 대시보드의 네이비/그레이 일변도 톤(이 제품은 업무 도구가 아니라 캐주얼 엔터테인먼트다).

**Key Characteristics:**
- 배경은 순백(`bg`), 브랜드 로즈(`primary`)는 전체 화면의 ~10% 이내로만 사용
- 카드/콘텐츠가 시각적 우선순위 1순위, 크롬(헤더/네비게이션)은 항상 얇고 동일하게 유지
- 상태(공개/비공개/이용제한/삭제, 초안 여부 등 도메인 상태 배지)는 `packages/ui`가 아닌 각 앱의 `entities/*`에서 이 팔레트의 `accent`/`destructive`/`muted` 롤을 조합해 표현(§techspec-overview.md §10)
- 절제된 모션, `prefers-reduced-motion` 항상 존중

## 2. Colors

순백 배경 위에서 잉크 블랙 하나가 위계를 만드는 무채색(모노크롬) 팔레트. 역할 구분은 색상(hue)이 아니라 명도 차이로만 하고, 유채색은 위험 액션(`destructive`)에만 남긴다 — 콘텐츠(썸네일, 대화 텍스트)가 화면에서 유일한 색이 된다.

### Primary
- **Ink Black (잉크 블랙)** (oklch(0.220 0.000 0)): 주요 CTA(플레이 버튼, 발행/제출), 링크, 포커스 링, 활성 토글. 채워진 배경 위에는 항상 흰 텍스트(`bg`)를 올린다.
- **Ink Hover** (oklch(0.380 0.000 0)) — `primary-deep`: `primary`의 hover/active 상태. 구현은 별도 토큰 없이 투명도로 만든다(`bg-primary/80` — 흰 배경 위 실효 명도가 이 값에 대응).

### Neutral
- **Pure White** (oklch(1.000 0.000 0)) — `bg`: 기본 배경. 채도 0의 순백을 그대로 쓰고 임의로 톤을 섞지 않는다.
- **Surface** (oklch(0.970 0.000 0)) — `surface`: 카드/패널/섹션 구분용, `bg`에서 `ink` 방향으로 아주 살짝만 이동한 옅은 회색.
- **Near-black Ink** (oklch(0.220 0.000 0)) — `ink`: 본문 텍스트. `bg` 대비 ≥7:1.
- **Muted** (oklch(0.530 0.000 0)) — `muted`: 보조 텍스트(캡션, 타임스탬프, 조회수). `bg` 대비 ≥4.5:1.
- **Border** (oklch(0.890 0.000 0)) — `border`: 구분선, 인풋 테두리.
- **Accent Surface** (oklch(0.930 0.000 0)) — `accent`: hover/선택 상태 배경, 배지 등 2차 강조용 표면. 유채색 강조가 아니라 옅은 회색 표면이다.

### Semantic
- **Destructive** (oklch(0.550 0.190 25)): 삭제/탈퇴/거부 등 위험 액션 전용 시스템 컬러. 무채색 팔레트에서 유일하게 허용되는 유채색이다.

### Dark Palette (`.dark`)

`html`의 `.dark` 클래스로 전환되는 무채색 다크 테마(globals.css `.dark` 블록과 동일 소스). 라이트의 명도 사다리(1.0 → 0.97 → 0.93 → 0.89)를 반전한 구조로, 다크에서는 위로 뜨는 레이어일수록 밝아진다.

- **Background** (oklch(0.160 0.000 0)): 기본 배경. 순수 검정이 아닌 near-black — 카드/팝오버 레이어 위계의 여지를 남긴다.
- **Foreground** (oklch(0.930 0.000 0)): 본문 텍스트. 순백이 아닌 소프트 화이트(bg 대비 ≈15.8:1) — 장시간 채팅 읽기 피로를 줄인다.
- **Card / Popover / Muted** (oklch(0.210 0.000 0)): 배경 위 첫 레이어.
- **Secondary / Accent** (oklch(0.260 0.000 0)): hover/선택 상태 배경, 배지 등 두 번째 레이어.
- **Border / Input** (oklch(0.300 0.000 0)): 구분선, 인풋 테두리.
- **Muted Foreground** (oklch(0.680 0.000 0)): 보조 텍스트. bg 대비 ≈6.7:1, secondary 위에서도 ≥4.5:1.
- **Primary** (oklch(0.930 0.000 0)) + **Primary Foreground** (oklch(0.160 0.000 0)): 라이트의 반전 — 다크에서 주요 CTA는 밝은 채움 + 어두운 텍스트. "primary = 최고 대비 채움" 규칙은 그대로 유지된다.
- **Destructive** (oklch(0.640 0.190 25)) + **Destructive Foreground** (oklch(0.160 0.000 0)): 어두운 배경에서 텍스트로 쓰일 때 ≥4.5:1이 되도록 빨강을 밝히고, 채움 위 텍스트는 primary와 같은 방식으로 어둡게 뒤집는다(밝힌 빨강 위 흰 텍스트는 AA 미달).
- **Ring** (oklch(0.930 0.000 0)): 포커스 링 — 라이트와 동일하게 primary를 따른다.

### Named Rules
**The One Accent Rule.** `primary`(잉크 블랙 채움)는 화면 안에서 "지금 누를 수 있는 액션"에만 쓴다 — 장식적 배경, 텍스트 그라디언트, 카드 전체 채우기에는 쓰지 않는다. 다크 모드에서는 채움이 소프트 화이트로 반전되지만 규칙은 동일하다.

## 3. Typography

**Display/Body/Label Font:** Pretendard (with `-apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif` fallback)

**Character:** 한글 가독성이 검증된 단일 휴머니스트 산세리프를 굵기(weight)만 바꿔가며 전 화면에 일관되게 사용한다 — 서로 다른 서체를 섞어 대비를 만들지 않는다(카테고리가 유사한 두 서체를 섞는 것보다 하나의 가변 굵기 패밀리가 더 안정적).

### Hierarchy
- **Display** (700, `clamp(1.5rem, 2.5vw, 2rem)`, 1.25): 빌더/설정 화면 섹션 제목 등 화면 내 최상위 제목.
- **Title** (600, 1.125rem, 1.35): 카드 제목(캐릭터/스토리 이름), 모달 헤더.
- **Body** (400, 0.9375rem, 1.6): 본문, 대화 메시지, 설명 텍스트. 한 줄 65-75자 내외로 줄바꿈.
- **Label** (500, 0.8125rem, 1.4): 버튼 텍스트, 폼 라벨, 배지.

### Named Rules
**The Single Family Rule.** 새 화면에 다른 서체 패밀리를 추가하지 않는다. 위계는 굵기·크기·자간으로만 만든다.

## 4. Elevation

기본은 플랫(그림자 없음) — 리스트 카드, 인풋, 버튼은 평평한 표면 위에서 `border`만으로 구분된다. 그림자는 오직 "현재 화면 위에 떠 있는" 상태(다이얼로그, 드롭다운, 토스트)에만 나타나는 반응형 신호로 사용한다.

### Shadow Vocabulary
- **Overlay** (`box-shadow: 0 12px 32px -8px oklch(0.220 0.020 330 / 0.18)`): Dialog, Sheet, DropdownMenu 등 배경 위로 뜨는 오버레이 전용.
- **Toast** (`box-shadow: 0 8px 20px -6px oklch(0.220 0.020 330 / 0.14)`): Toast/Sonner 알림.

### Named Rules
**The Flat-at-Rest Rule.** 카드/버튼/인풋은 정지 상태에서 그림자를 갖지 않는다. 그림자는 z축으로 떠 있는 엘리먼트(다이얼로그류)에만 붙는다.

## 5. Components

카주얼하지만 신뢰감 있는, "탭하면 바로 반응하는" 성격 — 라운드는 눈에 띄게 부드럽지만(6-16px) 장식적이지 않다.

### Buttons
- **Shape:** radius `md`(10px), 텍스트는 `label` 타이포
- **Primary:** `primary` 배경 + `bg`(흰색) 텍스트, hover 시 `primary-deep`
- **Ghost:** 배경 투명 + `ink` 텍스트, hover 시 `surface` 배경
- **Destructive:** `destructive` 배경 + 흰 텍스트 — 삭제/탈퇴/거부 액션 전용

### Inputs & Select
- **Shape:** radius `sm`(6px), `border` 테두리, 포커스 시 `primary` 2px 링(box-shadow, outline 대체 아님 — 접근성을 위해 `:focus-visible`에 항상 노출)

### Dialog
- **Shape:** radius `lg`(16px), `bg` 배경, Overlay 그림자, backdrop은 `ink`의 저채도 반투명 스크림
- 열기/닫기는 짧은 페이드+스케일(120-160ms, ease-out-quart), `prefers-reduced-motion`에서는 즉시 전환(크로스페이드)로 대체

### Toast
- **Shape:** radius `md`, Toast 그림자, `surface` 배경 — **사이드 스트라이프 보더 금지**(절대 금지 목록). 상태(성공/실패)는 좌측 아이콘 색상과 텍스트로만 구분한다.

## 6. Do's and Don'ts

- **Do** `primary`를 화면당 하나의 주 액션에만 집중해서 쓴다(플레이 버튼, 발행 버튼 등).
- **Do** 카드/리스트에서 `border` 한 줄로만 구분하고, 불필요한 그림자를 추가하지 않는다.
- **Do** 모든 인터랙티브 엘리먼트에 `:focus-visible` 링을 유지한다(전연령/접근성 정책).
- **Don't** `primary`/`accent`를 배경 전체 채우기나 텍스트 그라디언트로 쓰지 않는다.
- **Don't** Toast/Alert에 색상 사이드 보더를 쓰지 않는다.
- **Don't** 서로 다른 서체 패밀리를 섞지 않는다 — Pretendard 굵기 변화로만 위계를 만든다.

<!-- impeccable:note 이 SEED DESIGN.md는 자율 Ralph 루프(US-003) 중 실사용자 인터뷰 없이 PRODUCT.md + tasks/techspec-overview.md §10 + palette.mjs 시드(oklch(0.650 0.160 330), seed-103)를 근거로 작성되었습니다. packages/ui 구현에 착수하는 지금 시점의 토큰 소스로 사용하되, 실제 컴포넌트/페이지가 만들어진 뒤 `/impeccable document`를 다시 실행해 scan mode로 실제 토큰을 재확인하는 것을 권장합니다. -->
