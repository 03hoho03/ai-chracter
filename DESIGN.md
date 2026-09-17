---
name: 또나
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
  destructive-text: "oklch(0.690 0.190 25)"
  border: "oklch(0.300 0.000 0)"
  input: "oklch(0.520 0.000 0)"
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
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: "1.4286rem"
    letterSpacing: "normal"
  label:
    fontFamily: "Pretendard Variable, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: "1.1667rem"
    letterSpacing: "normal"
rounded:
  sm: "4.8px"
  md: "6.4px"
  lg: "8px"
  xl: "11.2px"
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
    height: "36px"
    padding: "0 16px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "oklch(0.720 0.180 0 / 0.8)"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "36px"
    padding: "0 16px"
  button-outline-hover:
    backgroundColor: "{colors.muted}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    height: "36px"
    padding: "0 16px"
  button-ghost-hover:
    backgroundColor: "{colors.muted}"
  button-destructive:
    backgroundColor: "oklch(0.640 0.190 25 / 0.1)"
    textColor: "{colors.destructive-text}"
    rounded: "{rounded.lg}"
    height: "36px"
    padding: "0 16px"
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
    rounded: "{rounded.lg}"
    height: "36px"
    padding: "0 12px"
  badge-status:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  badge-restricted:
    backgroundColor: "oklch(0.640 0.190 25 / 0.1)"
    textColor: "{colors.destructive-text}"
    rounded: "{rounded.full}"
    padding: "2px 8px"
  dialog:
    backgroundColor: "{colors.popover}"
    textColor: "{colors.popover-foreground}"
    rounded: "{rounded.xl}"
    padding: "24px"
---

# Design System: 또나

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
- 크롬은 sticky 헤더 하나(`h-14`)뿐 — 하단 탭바도, 사이드 레일도, 푸터도 없다(web 한정 — admin은 좌측 사이드바를 쓴다, §5 Navigation). **이 금지의 대상은 전역 크롬이다 — `<main>` 안에서 한 라우트의 콘텐츠를 여러 열로 나누는 것은 대상이 아니다**(판별 기준 §5 Navigation). 빌더 라우트(`/builder/*`)는 전역 헤더 대신 같은 56px 자리를 쓰는 전용 상단바(`BuilderTopBar`)로 바뀐다 — 크롬은 여전히 한 줄이다. **또 하나의 예외는 상세화면의 하단 고정 액션 바다**(D-7) — `lg` 미만에서 주 CTA(플레이) 하나를 화면 하단에 고정한다. 이것은 탭바·사이드 레일·푸터 같은 **상시 내비게이션**이 아니다: 화면 전환에 쓰이는 것이 아니라 그 화면의 **단일 전환 액션 하나만** 담는 바다. 이 예외는 상세화면 한 곳에 한정되며 **다른 화면으로 번지지 않는다** — 목록·채팅·빌더에 새 하단 바를 추가할 근거로 쓰지 말 것

## 2. Colors

**표면은 명도 하나로만 위계를 만들고(무채색 사다리), 색은 강조 지점에만 얹는다.** 레이어 구분은 여전히 색상(hue)이 아니라 밝기 차이로만 하고, 유채색은 `primary`/`ring`·`destructive`·사용자 콘텐츠 셋에만 남긴다. 프론트매터는 **기본 테마인 다크**를 담는다. 두 팔레트 모두 `packages/ui/src/styles/globals.css` 한 곳에서만 정의된다.

아래 본문의 oklch 값은 `globals.css`와 **문자열까지 같게** 적는다(프론트매터 블록만 도구 규약상 3자리 정규화 표기 — 같은 값이다). 문서와 코드가 어긋났는지는 grep 한 번으로 확인할 수 있어야 한다.

### Primary
- **Pink-Red Accent (핑크-레드 강조)** — `primary`(= `ring`, 라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`): 주요 CTA(플레이, 발행/제출), 사용자 말풍선, 포커스 링·보더, 활성 토글, 체크박스·스위치의 on 상태. **이 시스템에서 유일한 유채색 솔리드 채움이다** — `destructive`가 언제나 `/10` 틴트인 것과 형태로 갈린다.
- **채움 위 텍스트는 항상 `primary-foreground`로 뒤집는다**(라이트 `oklch(1 0 0)` / 다크 `oklch(0.16 0 0)`): 라이트 **6.70:1** / 다크 **7.18:1**. 라이트 채움이 더 어두운 것은 그 위에 흰 텍스트를 얹기 때문이다.
- **브랜드 색을 라이트·다크 단일값으로 합치지 않는다 — 검토 후 기각했다**(2026-09-11, `design-system-goal-prompt.md` D-15). 네 조건(양 테마의 채움 위 텍스트 ≥4.5:1, 채움 대 배경 ≥3:1)을 전부 만족하는 단일값 대역 `oklch(L 0.52~0.54)`은 **존재한다** — 그러니 이건 접근성 때문에 못 하는 게 아니다. 기각한 이유는 **다크에서 채움이 배경에서 떨어져 나오는 정도가 7.18:1 → 3.44:1**(카드 위에 앉는 플레이 CTA는 **3.14:1**)로 반토막 나고, 활성 칩의 상대 휘도가 **0.327 → 0.130**으로 떨어지기 때문이다(A/B 렌더 + canvas 실측). "불 꺼진 방의 유일한 빛"에서 유일한 유채색 솔리드 채움이 빛의 60%를 잃는 거래다. **레퍼런스 둘 다 이 문제를 풀지 않았다** — 크랙은 단일값을 쓰되 양쪽 모드 3.43:1로 AA를 포기했고, 케이브덕은 다크 전용이라 라이트 제약을 진 적이 없다(그 자신도 채움 대 배경은 2.83:1이다). **이 결정은 "분홍 채움 위 흰 글자"와 같은 하나의 결정이다** — 흰 글자를 얻으려면 다크 `primary`의 L을 0.54 이하로 내려야 하고 그게 곧 단일값 대역이다.
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
| `border` | oklch(0.300) | oklch(0.890) | **구조 구분선** — 카드 테두리, 헤더 밑줄, 섹션 구분, 점선 빈 상태 |
| `input` | oklch(0.520) | oklch(0.620) | **컨트롤 식별 보더** — 인풋·텍스트에어리어·셀렉트·체크박스·outline 버튼·선택 안 된 토글, 그리고 스위치의 off 트랙(`bg-input`) |
| `muted-foreground` | oklch(0.680) | oklch(0.530) | 보조 텍스트 — 캡션, 타임스탬프, 조회수 |
| `foreground` | oklch(0.930) | oklch(0.220) | 본문 텍스트 |

측정된 대비(WCAG 2.x, sRGB 변환 기준):
- 다크 `foreground` on `background`: **15.79:1** / 라이트 `foreground` on `background`: **17.31:1**
- 다크 `muted-foreground` on `background`: **6.74:1**, on `secondary`: **5.39:1** — 두 레이어 모두 AA 통과
- 라이트 `muted-foreground` on `background`: **5.28:1**, on `card`: **4.84:1** — 통과. 단 **on `accent`(0.930)에서는 4.30:1로 AA 미달**이므로, 라이트에서 `accent` 표면 위에 `muted-foreground`로 본문을 올리지 않는다(배지처럼 큰 텍스트가 아닌 이상).

**`border`와 `input`은 값이 다르다 — 사다리에서 갈라져 나온 유일한 무채색 토큰이다(US-004).** 둘은 규범이 다르다: `border`가 그리는 구분선·카드 테두리는 장식이라 WCAG 대비 요건이 없지만, `input`이 그리는 컨트롤 테두리는 **비텍스트 대비 1.4.11(3:1)**을 진다 — 인풋·outline 버튼·선택 안 된 토글은 내부 채움이 페이지 배경과 `1.0000`이라 그 한 줄이 "여기 컨트롤이 있다"는 **유일한 신호**이기 때문이다. 사다리 값(0.300/0.890)으로는 **1.4312 다크 / 1.3845 라이트**로 절반도 안 됐다.
- 고친 값의 실측(스크린샷 픽셀 디코드): 인풋 보더 대 `background` **3.5403 다크 / 3.6408 라이트**, 대 `card`(=`popover`·`muted`) **3.2344 / 3.3395**. 스위치 off 트랙(`bg-input`)과 그 위 흰 썸(`bg-background`)도 같은 값을 얻는다(전 1.4312 → 후 3.5403).
- **`secondary`·`accent`(다크 0.260 / 라이트 0.930) 표면 위에서는 2.8276 / 2.9714로 여전히 미달이다.** 그 두 표면 위에는 보더로만 식별되는 컨트롤을 올리지 않는다 — 올려야 한다면 채움이나 링을 함께 준다.
- **컨트롤 테두리에 `border-border`를 쓰지 말 것.** 손으로 복사한 셸(파일 업로드 라벨, 아이콘·컬러 피커 트리거, 목록형 선택 행)이 이 규칙을 조용히 새게 만든다 — 인터랙티브하면 `border-input`, 구조면 `border-border`다. 예외는 **클릭 카드**(`ContentCard`, `BuilderTypeSelectPage`)로, 거기서는 썸네일·제목·hover·포커스 링이 함께 식별을 지므로 `border-border`를 유지한다(§5 Cards).

### Semantic
- **Destructive (경고 레드)** — 다크 oklch(0.640 0.190 25) / 라이트 oklch(0.550 0.190 25): 삭제/탈퇴/거부/이용제한. `primary`와 함께 시스템 유채색 둘 중 하나이며, 둘은 hue(25 대 0)와 **형태**로 갈린다 — destructive는 언제나 틴트, primary는 솔리드 채움이다. 다크에서 빨강을 밝힌 것은 텍스트 대비를 위해서이며(on `background` **5.27:1**), 그 대가로 **밝힌 빨강 위 흰 텍스트는 3.68:1로 AA에 미달한다** — 그래서 `destructive-foreground`도 함께 어둡게 뒤집는다(0.160, 대비 5.27:1). 토큰을 조정할 때 이 쌍을 반드시 함께 유지할 것.
- **실제 구현에서 destructive는 채움이 아니라 틴트다**: 버튼도 배지도 `bg-destructive/10 text-destructive-text`를 쓴다. 어두운 방에서 솔리드 레드 블록은 그 자체로 놀람이다.
- **Destructive text (경고 레드 · 텍스트 전용)** — 다크 oklch(0.690 0.190 25) / 라이트 oklch(0.490 0.190 25): **틴트 위에 얹는 글자와 글리프는 `--destructive`가 아니라 이 토큰을 쓴다.** 채움 쪽(`bg-destructive/5`·`/10`·`/20`, `border-destructive/30`, `ring-destructive/20`)과 **솔리드 채움 위의 `destructive-foreground` 반전 쌍**은 `--destructive` 그대로다 — 둘을 갈라 둔 이유가 그것이다.
  - 왜 갈랐나: 한 토큰이 글자와 틴트를 겸하면 대비를 올리는 순간 틴트 색까지 함께 움직인다. `--destructive`(라이트 0.55 / 다크 0.64)는 평평한 `background` 위에서만 AA를 아슬아슬하게 넘겼고(라이트 **4.5672** / 다크 4.8402 — 앞은 이번 런에서 재현한 실측, 뒤는 저장소 공표값), `bg-popover`처럼 **사다리 한 칸 안쪽 표면**에 얹히면 rest 4.2059 / 4.3824, hover(`/20`)에서 **3.6035 / 3.8252**까지 떨어졌다.
  - 갈라 낸 뒤 실측(canvas `getImageData`, 전이 정착 후): 최악 조합인 **hover `/20` over `popover`가 라이트 4.6907 / 다크 4.6346**, `/10` over `popover`가 5.4748 / 5.3097, 평평한 `background` 위가 5.9451 / 5.9024다. 틴트 픽셀은 전후 동일하다(A/B로 확인 — `/5` `/10` `/20` 합성 결과가 라이트·다크 모두 바이트까지 같다).
  - 명도는 이 이상 못 민다: 라이트 0.49에서 hue 25의 sRGB 게멋 상한 chroma가 0.1986, 다크 0.69에서 0.1995라 현재 값 0.19가 이미 상한 바로 아래다.

### Tertiary
- **스탯 스와치(User-chosen swatches)** — `packages/ui/src/lib/color-palette.ts`의 10색 고정 팔레트(rose/orange/amber/lime/emerald/teal/sky/indigo/violet/fuchsia, 예: oklch(0.62 0.19 350)). **UI 팔레트가 아니라 사용자 데이터다** — 채팅방 스탯 게이지와 컬러 피커에서 사용자가 직접 고른 값이며, 테마에 따라 변하지 않는다. 시스템 토큰으로 승격하지 말 것.
- **스크림(Scrim) — `--scrim` oklch(0 0 0) / `--scrim-foreground` oklch(0.930 0 0)**: 아트워크 위에 캡션을 얹는 자리 전용이고, **이 쌍만 `.dark`에서 덮이지 않는다**(globals.css `:root`에만 있다). 아래 깔린 것이 팔레트가 아니라 임의의 이미지라, 테마를 따라 뒤집으면 반드시 한쪽이 깨진다 — 스크림은 테마와 무관하게 어두운데 그 위 글씨만 라이트에서 어두워지기 때문이다. `--scrim-foreground`의 0.930은 밝기 예산 규칙의 천장과 같은 값이라 순백 금지를 지킨다. **쓸 때는 `bg-scrim/70` 불투명 밴드다** — 그래야 아트워크가 무엇이든 최악(순백 픽셀)에서 6.93:1이 보장된다. 옅은 그라데이션(`bg-gradient-to-t from-scrim/60`)으로 깔면 글자 윗단에서 알파가 0.28까지 떨어져 그 보장이 사라진다(실측: 다크 1.65:1 · 라이트 1.67:1로 양쪽 다 미달이었다). 지금 쓰는 곳은 `GenerateImagesStyleGrid`의 스타일 타일 이름표 하나다.

### Named Rules
**The Brightness Budget Rule (밝기 예산 규칙).** 화면은 방의 유일한 광원이다. 다크 테마에서 `foreground`(0.930)보다 밝은 값은 **존재하지 않는다** — 순백(oklch 1.000)은 다크에서 금지다. 밝은 표면은 예산이고, 단위는 **면적**이다. 하지만 실제로 지켜지는 제약은 치수 상한이 아니다 — `CharacterPlayButton.tsx`·`StoryDetailBody.tsx`의 플레이 버튼은 `primary` 솔리드 채움에 `h-12 w-full`이라 데스크톱 472×48 ≈ 22,700px²로 `h-8` 버튼의 약 15배지만 예산을 어기지 않는다, 그 화면의 유일한 전환 지점이기 때문이다(`design-system-goal-prompt.md` §3-0). 지켜지는 규칙은 **"밝은 면적은 예산이고, 한 화면에서 지금 눌러야 할 단 하나에만 쓴다"**이다: 무채색 variant(`outline`·`ghost`·`secondary`)의 확대는 이 예산을 전혀 쓰지 않고, `primary` 솔리드 확대는 **화면당 하나**라는 제약으로 관리한다 — 치수 상한이 아니다. `destructive`는 항상 `/10` 틴트라 애초에 이 예산 밖이다. **두 가지 오독을 차단한다**: ① "단위가 높이니 패딩은 공짜다"가 아니다 — 원문 단위는 면적이라 가로로 넓혀도 그만큼 예산을 쓴다. ② "규칙이 거짓이니 밝기는 신경 안 써도 된다"가 아니다 — 거짓이었던 건 `h-8`이라는 **수치 상한 주장**이지 예산 개념 자체가 아니다. 핑크-레드로 바뀐 뒤에도 다크 `primary`의 L(0.72)은 이 천장 아래에 있다.

**The Inverted Ladder Rule (반전 사다리 규칙).** 다크에서는 위로 뜨는 레이어일수록 밝아진다(0.160 → 0.210 → 0.260 → 0.300). 라이트에서는 정확히 반대다(1.000 → 0.970 → 0.930 → 0.890). 새 레이어를 추가할 때 이 사다리에 없는 중간값을 발명하지 말 것.

**The One-Accent Rule (강조는 하나뿐 규칙).** 색이 존재할 수 있는 곳은 셋뿐이다 — 강조 지점(`primary`/`ring`), 사용자 콘텐츠(썸네일, 스탯 스와치), 위험 액션(`destructive`). 배경·카드·보더 사다리와 그 위의 텍스트·배지·비활성 컨트롤은 끝까지 무채색이다. 새 UI 색(성공 그린, 정보 블루, 브랜드 세컨더리)을 발명하지 말 것 — 상태는 아이콘과 텍스트로 구분한다. 그리고 강조는 **하나**라는 뜻이기도 하다: 한 화면에서 `primary`로 칠할 것을 고를 때 "지금 누를 수 있는 것"과 "지금 내가 한 말"(사용자 말풍선) 밖으로 번지면, 썸네일 한 장이 유일하게 빛난다는 전제가 무너진다.

## 3. Typography

**Display / Title / Body / Label Font:** Pretendard Variable (with `-apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif`)

`--font-heading`은 `--font-sans`의 별칭이다(`globals.css`) — 제목용 별도 서체는 존재하지 않으며, 앱 코드에서 `font-heading`은 한 번도 쓰이지 않는다.

**Character:** 한글 가독성이 검증된 단일 휴머니스트 산세리프를 굵기(weight)만 바꿔 전 화면에 쓴다. 실제로 코드에 존재하는 굵기는 셋뿐이다 — medium(500) / semibold(600) / bold(700). 크기 스케일도 `text-2xl`(1.5rem)에서 멈춘다: 이 제품에는 히어로가 없고, 가장 큰 글자도 페이지 제목이다.

### Hierarchy
- **Display** (700, 1.5rem/2rem, -0.025em): 페이지 제목(h1) 전용. 화면 내 최상위. **h1이 아닌 곳에 쓰지 않는다 — 예외가 0이다**: 앱의 `text-2xl` 8곳 중 7곳이 h1이고 나머지 하나는 아바타 이니셜 글리프다. (이 줄은 한때 "마이페이지 섹션 제목"을 포함했다. 그건 규칙이 아니라 한 파일의 예외였고 — 그 화면의 h1과 h2는 계산된 속성 580개가 **전부 일치**해 헤딩으로 훑으면 넷이 동일하게 읽혔다 — US-013이 그 h2 셋을 Title로 내리면서 사라졌다.)
- **Title** (600, 1.25rem/1.75rem, -0.025em): 인증 화면 제목, 모달 헤더, 카드 제목, **설정 섹션 제목(h2)**. 페이지 제목 아래 한 단계가 필요한 자리는 전부 여기다.
- **18px 소제목** (`text-lg`, 1.125rem/1.75rem, 굵기는 자리에 따라 `font-semibold`(카드·목록·빈 상태 제목) 또는 `font-medium`(Dialog/Sheet/AlertDialog 제목)): Title(20px)보다 한 단계 낮은 강조가 필요한 소제목. **D-9 이전엔 이 문서에 없던 6번째 크기였다** — 당시 `text-base`(Tailwind 기본값, 16px)로 17곳이 손조립돼 있었는데, D-8이 Body(`--text-sm`)를 16px로 올리면서 `text-base`와 값이 같아져 위계가 붕괴할 뻔했다. D-9가 그 17곳을 `text-lg`(18px)로 옮기며 이 자리를 사다리의 정식 티어로 승격했다(`design-system-goal-prompt.md` D-9).
- **Body** (400, 1rem/1.4286rem): 본문, 대화 메시지, 설명. 앱에서 여전히 가장 많이 쓰이는 크기다(재측정 `text-sm` 150회 — `grep -rnE '\btext-sm\b' apps/web/src --include='*.tsx'`, 주석 제외 — Label(`text-xs`) 128회를 근소하게 앞선다)이며 **사실상의 기본값**이다. 산문은 65-75**자**(문자 수 기준 — `ch` 단위가 아니다, 한글은 글리프가 전각이라 두 단위가 갈린다)에서 줄바꿈이 규범이다. 채팅 실측은 1512px에서 61~70자로 이 규범 안에 들고, 390px는 폰 폭이 물리적으로 좁아 규범 달성이 아니라 낭비 제거가 목표다(`design-system-goal-prompt.md` §3-3-3).
- **Label** (500, 0.875rem/1.1667rem): 폼 라벨, 캡션, 메타(조회수·타임스탬프), 에러 텍스트.
- **Badge** (500, 0.75rem = 12px): 상태 배지 전용. `text-xs`(현재 Label, 14px)는 배지 안에서 너무 크다. **Tailwind 숫자 사다리(xs/sm/base…) 밖의 값이지만 임의값이 아니라 토큰이다** — `globals.css`의 `--text-badge`로 두고 호출부는 `text-badge`를 쓴다. (한때 호출부 6곳이 `text-[11px]`를 손으로 적었고 이 줄은 "이 한 티어를 위해 스케일을 늘리지 않았다"로 그걸 정당화했다. 같은 임의값이 6번 반복되면 승격이 규칙이고, 사다리에 칸을 끼우는 것과 **이미 이름 붙은 티어를 시맨틱 토큰으로 실체화하는 것**은 다르다 — `text-2xs`가 아니라 `text-badge`인 이유다. 줄높이는 짝으로 두지 않았다: 이전 `text-[11px]`도 font-size만 설정했으므로 여기서 정하면 6곳의 렌더가 바뀐다. 값은 D-8로 11px→12px가 됐다.)

### Named Rules
**The Single Family Rule (단일 서체 규칙).** 새 화면에 다른 서체 패밀리를 추가하지 않는다. 위계는 굵기·크기·자간으로만 만든다. `font-medium` / `font-semibold` / `font-bold` 셋 밖의 굵기를 도입하지 말 것.

**The No-Hero Rule (히어로 없음 규칙).** `text-2xl`(1.5rem)이 천장이다. 이 제품은 랜딩 페이지가 아니라 사용자가 이미 들어와 있는 도구다 — 큰 글자로 설득할 대상이 없다. clamp()나 vw 기반 유동 타이포는 쓰지 않는다(모든 크기는 고정 rem).

## 4. Elevation

**이 시스템은 사실상 그림자가 없다.** 깊이는 그림자가 아니라 §2의 명도 사다리(tonal layering)로 표현한다 — 다크에서 카드가 배경 위에 있다는 것은 그림자가 아니라 `card`(0.210)가 `background`(0.160)보다 밝다는 사실로 전달된다. **예외는 카드 자체가 주 인터랙션인 경우다** — 그때는 hover가 보여야 해서 표면이 `background`로 내려가고 깊이를 `border` 한 줄이 대신한다(§5 Cards). 이것이 "불 꺼진 방"에서 옳은 선택이다: 어두운 방에서 드리운 그림자는 보이지도 않고, 보이게 만들려면 배경을 더 어둡게 깎아야 하는데 그럴 여지가 없다.

앱 전체에 그림자는 **5개뿐이며**, 그중 3개는 화면 위로 떠 있는 팝오버(단축어 자동완성, 컬러 피커, 아이콘 피커)다. 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다.

### Shadow Vocabulary
- **Floating panel** (`shadow-md` + `ring-1 ring-foreground/10`): 트리거 위에 떠서 열리는 커스텀 팝오버 전용. 그림자만으로는 다크에서 경계가 보이지 않으므로 **반드시 `ring`과 함께 쓴다** — 이 조합이 다크에서 실제로 경계를 만드는 것은 ring 쪽이다.
- **Overlay scrim** (`bg-black/10` + `backdrop-blur`): Dialog/Sheet/AlertDialog 배경. **라이트/다크 공통 하드코딩이며 의도된 것이다**(US-131 판정) — 다크에서는 블러가 배경 분리를 담당한다. 시맨틱 토큰으로 바꾸지 말 것.

### Named Rules
**The Flat-at-Rest Rule (정지 시 평평 규칙).** 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다. 그림자는 z축으로 실제로 떠 있는 엘리먼트에만 붙는다. 감사 테스트: 새 컴포넌트에 `shadow-*`를 쓰려 한다면, 그것이 클릭으로 열려서 다른 것 위에 뜨는 물건인지 자문하라. 아니라면 `border`를 쓴다.

**The Ring-Not-Shadow Rule (그림자 대신 링 규칙).** 다크에서 떠 있는 표면의 경계는 그림자가 아니라 `ring-1 ring-foreground/10`이 만든다. 그림자를 더 진하게 키워 경계를 만들려 하지 말 것 — 어두운 배경 위에서는 아무리 키워도 보이지 않는다.

## 5. Components

캐주얼하지 않고 **조용하다**. 컴포넌트는 작고(기본 높이 36px), 라운드는 부드럽지만 장식적이지 않으며, 반응은 즉각적이되 과장이 없다. 밤에 한 손으로 쓰는 물건의 성격이다.

**반경 정책: 같은 높이 티어는 같은 반경을 쓴다** — 32px 티어(`Button`의 `sm`·`icon-sm`, `SelectTrigger sm`)는 `lg`(8px), 24px 티어(`xs`·`icon-xs`)는 `min(md,10px)`(6.4px). 반경 캡이 따로 남아 있으면 같은 32px 안에서 모서리가 갈린다. **`Toggle`은 이 정책의 예외다**(D-13) — 필터 칩과 액션 버튼을 형태로 가르기 위해 `rounded-full`(pill)을 쓴다. 같은 32px 티어 안에서 `Button`/`SelectTrigger`와 반경이 달라지는 것은 실수가 아니라 "칩과 버튼은 다른 물건"이라는 신호다(아래 §Toggles) — `apps/web/CLAUDE.md`가 "`SelectTrigger size="sm"`은 `ToggleGroupItem sm`과 픽셀상 같다"고 적은 것은 D-13 **이전** 값 기준이라 이제 반경 항목은 더 이상 맞지 않는다(높이 32px는 여전히 같다).

### Buttons
- **Shape:** radius `lg`(8px; `xs`/`icon-xs`만 6.4px, §반경 정책), 기본 높이 `h-9`(36px). 크기 4단계(`xs` 24px / `sm` 32px / `default` 36px / `lg` 40px)와 아이콘 전용 4종. 48px(`h-12`, 플레이 버튼 2곳)은 이 사다리에 없는 호출부 오버라이드 예외다.
- **Primary:** 핑크-레드 `primary` 채움 + `primary-foreground` 텍스트, hover 시 `bg-primary/80`. 다크에서는 밝힌 핑크 + 어두운 텍스트, 라이트에서는 어두운 핑크 + 흰 텍스트 — **규칙은 "채움 위 텍스트를 뒤집는다"로 동일하다**(§2 Primary).
- **Outline:** `border-input` + `background`, hover 시 `bg-muted`. **보더는 `border`가 아니라 `input`이다** — 채움이 배경과 같아 이 한 줄이 유일한 식별 신호이고 3:1을 진다(§2 Neutral).
- **Secondary:** `secondary` 채움, hover는 `color-mix(in oklch, var(--secondary), var(--foreground) 5%)` — 사다리를 벗어나지 않도록 토큰에서 파생시킨다.
- **Ghost:** 투명, hover 시 `bg-muted`.
- **Destructive:** **채움이 아니라 틴트다** — `bg-destructive/10 text-destructive-text`, hover 시 `/20`. 솔리드 레드 버튼은 이 시스템에 존재하지 않는다. **포커스는 하우스 레시피의 hue만 바꾼다** — `focus-visible:border-destructive` + `ring-destructive/50`. 알파를 낮추지 말 것: 보더 40% · 링 20%였을 때 포커스가 **어느 쪽으로도 보이지 않았다**(링 대 배경 1.2371 다크 / 1.3694 라이트, 링 대 자기 채움 1.1312 / 1.1728 — 이 앱에서 포커스가 사실상 안 보이는 유일한 컨트롤이었다). 불투명 보더는 자기 채움 대비 **4.8431 / 4.5795**, 배경 대비 **5.2933 / 5.3328**이다.
- **Link:** `text-primary` + underline-offset-4.
- **Press feedback:** `active:translate-y-px` — 1px 눌림. 이게 이 시스템의 유일한 촉각 신호다(팝오버를 여는 버튼은 제외).
- **Focus:** `focus-visible:ring-3 ring-ring/50` + `border-ring`. 항상 노출한다. **3:1을 지는 건 50% 링이 아니라 불투명 1px 보더다** — 링은 페이지 배경 대비 2.5757 다크 / 2.5511 라이트지만 보더는 자기 채움 대비 **7.1768 / 6.7011**이다(실측). 그래서 이 레시피는 **보더가 살아 있는 한** 성립한다. **채움이 `primary` 솔리드면 무너진다** — 보더가 채움과 같은 색이 되어 사라지므로 링을 불투명으로 올린다(아래 §Toggles). `/10` 틴트 채움(destructive, `toggle` `list`)은 보더가 남으므로 hue만 갈아끼우면 된다.

### Toggles (선택 칩 / 목록형 선택지)
단일선택 토글은 `packages/ui/src/components/toggle.tsx`의 `toggleVariants` 하나에서만 정의된다 — 장르 필터, 헤더의 캐릭터/스토리, 테마 선택, 빌더의 시작설정·공개범위가 전부 같은 프리미티브다.

- **Shape:** 칩은 `sm`(높이 32px), 그 밖은 `default`(36px) — 둘 다 radius `rounded-full`(pill, D-13)로 같다. 테두리 `border-input`, 배경 투명. **§반경 정책의 예외다** — 크랙·케이브덕 둘 다 필터 칩(pill/8~16px)과 액션 버튼(4px)을 반경으로 가르는데, 이 프리미티브는 D-13 전까지 `Button`과 같은 `lg`(8px)를 써서 형태로 안 갈렸다. 헤더의 캐릭터/스토리 토글은 **더 이상 pill이 아니다** — 크랙·케이브덕처럼 글자색만으로 활성/비활성을 가르는 텍스트 탭으로 바꾸겠다는 예고가 2026-09-14 실행됐다(MR-2). 그 토글은 이제 `variant="tab"`을 쓴다(아래). **`variant="list"`는 pill을 안 받고 `lg`(8px)로 남고, `variant="tab"`은 pill도 `lg`도 아닌 `rounded-md`다** — 아래 각각 참조.
- **선택 상태는 `primary` 솔리드 채움 + `primary-foreground` 텍스트**다(§2 Primary가 "활성 토글"을 primary 용처로 명시). 다크 **7.18:1** / 라이트 **6.70:1**, hover(`bg-primary/80`)에서도 **4.90:1** / **4.77:1**로 AA를 유지한다.
- **비활성 글자는 `text-muted-foreground`다**(D-13). 이전엔 상속받은 `foreground`(0.930, 다크에서 사실상 밝기 천장)를 그대로 썼는데, 크랙·케이브덕은 비활성 → 활성 방향으로 밝기가 오르는 반대 구조다(크랙 탭 43%→96%, 케이브덕 탭 36%→100%). 비활성이 이미 천장이면 활성에서 올릴 데가 없어 방향이 반대로 읽혔고, 홈 화면에서 선택 안 된 장르 칩 10개가 전부 그 천장을 쓰는 건 §2 밝기 예산 규칙("밝은 면적은 예산이고 한 화면에서 지금 눌러야 할 단 하나에만 쓴다")과 정면으로 어긋났다. 대비 실측(canvas 변환): 다크 on `background` **6.74:1** / on `card` **6.16:1**, 라이트 on `background` **5.25:1** / on `card` **4.82:1** — 전부 AA(4.5:1)를 넘는다. **보더(`border-input`)는 그대로 둔다** — 이 사다리에서 3:1을 넘는 유일한 무채색 값이라(`border`는 다크 1.43:1 / 라이트 1.38:1로 이미 미달, §2 Neutral) 더 낮출 자리가 없다.
- **선택 상태를 `bg-muted`로 칠하지 말 것.** 상류 shadcn 기본값이지만 이 시스템에서 그 값은 `background`와 명도가 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160, 약 **1.3:1**) 선택이 보이지 않고, `hover:bg-muted`와 색이 같아 선택 안 된 항목에 마우스만 올려도 구별되지 않는다. `shadcn add toggle`로 재생성하면 이 값이 되돌아온다.
- **`variant="list"` — 넓은 행이 세로로 쌓인 목록형 선택지**(신고 사유 등)**에만 쓴다.** 이 형태에 솔리드 채움을 쓰면 같은 화면의 primary CTA와 같은 크기·같은 색 덩어리가 둘이 되어 무엇이 액션인지 흐려진다(밝기 예산 규칙 — 화면당 `primary` 솔리드 채움은 하나뿐이어야 한다). 그래서 `border-primary` + `text-primary` + `bg-primary/10` 틴트로만 표시하고(선택 행 텍스트 대비 **5.24:1**), 솔리드 채움은 CTA에 남긴다. **D-13의 두 변경(pill · 비활성 글자 다운)을 둘 다 받지 않는다** — `lg`(8px)와 `text-foreground`로 남는다. pill을 안 받는 이유는 D-13이 가르려던 축이 *칩 대 액션 버튼*인데 `list`는 애초에 칩이 아니기 때문이다: 신고 모달의 행은 호출부가 `h-11`로 올려 **352×44px**이라 pill을 주면 반경이 **22px**이 되고, 바로 아래 CTA는 **36px·8px**이라 선택지 쪽이 더 버튼처럼 읽혀 의도가 뒤집힌다(실측). 글자 다운을 안 받는 이유도 같은 뿌리다 — 필터 칩은 이미 뜻을 아는 항목을 반복해서 훑는 자리라 낮춰도 되지만, `list`는 처음 보는 여러 문장을 전부 읽고 하나를 고르는 자리다. 대비 수치가 AA를 넘어도 그게 "읽는 부담이 없다"를 보장하진 않는다.
- **`variant="tab"` — 라우트 전환 탭 하나뿐인 자리에 쓴다**(헤더의 캐릭터/스토리, MR-2). **필터 칩에는 쓰지 않는다.** 채움·보더 없음, `relative`(베이스 `toggleVariants`엔 없어 `tab`이 직접 선언 — 없으면 `after:absolute` 밑줄이 포지셔닝 컨텍스트를 상위(헤더)로 흘려 엉뚱한 위치에 찍힌다), `rounded-md`(포커스 링 모양용), 비활성 `text-muted-foreground`, 활성 `text-foreground` + `after:` 의사요소 밑줄(`h-0.5 bg-foreground`, `opacity` 전환, `motion-safe:`). 활성 표시가 `primary`가 아니라 `foreground`인 것은 One-Accent Rule과 `Tabs variant="line"`의 어휘를 그대로 따르는 것이다. **밑줄 위치는 `after:bottom-0`이다 — `tabs.tsx`의 `bottom-[-5px]`를 베끼지 않는다.** 그 −5px는 `TabsList`의 `h-9`+`p-[3px]`와 트리거 `h-[calc(100%-1px)]`가 만드는 **약 3.5px 트로프**를 상쇄하는 값인데(박스모델 계산) `ToggleGroup`엔 그 패딩 트로프가 없다. 36px 아이템이 56px 헤더에 중앙 정렬되면 아래 여유가 10px뿐이라 −5px를 그대로 쓰면 밑줄이 헤더 `border-b`와 3px 거리에서 이중선으로 읽힌다. **밑줄은 헤더 `border-b` 위 11px에 앉는다**(1512·390·320px 스크린샷 확인, V-3 통과) — 이중선으로 안 읽힌다. `tab`이 활성 솔리드 채움이 없다는 사실은 포커스 오버라이드 생략과 **직접** 연결된다: 포커스 표시의 하중은 `border border-transparent`가 진다 — `focus-visible:border-ring`이 그걸 불투명 핑크로 바꿔 헤더 배경 대비 **7.18:1**(≥3:1 통과)이 되고, **50% 링 단독은 2.58:1로 미달**이다(V-4 실측). `default`/`outline`/`list`가 필요했던 **불투명 포커스 링 오버라이드(`data-[state=on]:focus-visible:ring-ring`)가 `tab`엔 필요 없는 이유는 채움이 없어 `border-ring`이 사라지지 않기 때문**이다 — `default` 등에서는 그 보더가 `primary` 채움과 같은 색이 되어 지워졌지만(아래 포커스 링 문단), `tab`엔 채움 자체가 없어 그 문제가 없다. 활성 텍스트 대비는 **15.86:1**(`text-foreground`) / 비활성 **6.74:1**(D-13 값 재사용, 다크 on `background`) — 이전 pill 형태(핑크 채움 위 반전 글자)는 활성 **7.18:1**이었다. **`px-2`는 `variant` 문자열이 아니라 `compoundVariants`로 들어간다**(`{variant:"tab", size:"default", class:"px-2"}`) — cva는 `base + variant + size + compoundVariants` 순으로 이어붙이고 twMerge는 **뒤에 오는 것을 남기므로**, `variant` 문자열에 넣은 `px-2`는 `size.default`의 `px-4`에 **진다**(2026-09-15, 실제 패키지로 확인).
- **감사 테스트:** 토글에 새 선택 표시를 만들려 한다면, 그 항목이 버튼만 한 크기인지 자문하라. 그렇다면 기본 채움을 그대로 쓰고, 한 줄을 가득 채우는 크기라면 `list`를 쓴다.
- **좌측 드로어(§Navigation)의 캐릭터/스토리 전환은 `variant="tab"`이 아니라 `variant="outline"`인 가로 pill 쌍이다**(MR-14) — 감사 테스트대로 라벨 3자짜리 버튼 크기라 `list`가 아니라 기본 채움(outline)을 쓴다. `ContentTypeToggle`이 `variant` prop(`"tab" | "outline"`)으로 헤더·드로어 두 자리를 겸한다 — 재클릭 시 `""` emit 가드와 `navigate({to:"/"})`를 두 컴포넌트로 복제하면 한쪽이 조용히 새는 실패 모드(17곳 중 2곳만 맞았던 선례와 같은 뿌리)를 반복하기 때문이다. **아직 코드가 없다** — 드로어 화면 자체는 `main-refact-progress.md` S3b에서 만든다.
- **호출부에 선택 상태 클래스를 직접 붙이지 말 것** — 프리미티브에 없는 규칙을 호출부마다 문자열로 붙이면 새로 추가되는 화면이 조용히 빠진다(실제로 17곳 중 2곳만 맞았던 적이 있다).
- **선택된 토글의 포커스 링은 불투명해야 한다**(`data-[state=on]:focus-visible:ring-ring`). §Buttons의 기본 레시피(`ring-ring/50` + `border-ring`)는 **배경 위에서만** 성립한다 — `primary` 솔리드 채움 위에서는 `border-ring`이 보더를 채움과 **같은 핑크**로 바꿔 rest의 회색 윤곽을 지워 버리고(라이트 **1.0000** / 다크 **1.0437**), 남는 50% 링은 페이지 배경 대비 **2.5757 다크 / 2.5511 라이트**로 WCAG 1.4.11의 3:1에 미달한다(포커스 on/off 픽셀 diff 실측, 두 리뷰어 독립 일치). **이 수치는 포커스가 정착한 뒤 재야 한다** — `transition-all` 0.15s가 box-shadow까지 애니메이션해서 Tab 직후 읽으면 전이 중간값(α≈0.486, 2.4724)이 잡힌다. ToggleGroup은 roving tabindex라 **Tab이 닿는 칩은 언제나 선택된 칩**이므로 이건 엣지가 아니라 기본 포커스 상태다. 불투명 링은 같은 픽셀이 **7.1768 다크 / 6.7011 라이트**가 되고 rest 상태는 1픽셀도 바뀌지 않는다.

### Cards / Containers
- **Corner Style:** radius `xl`(11.2px).
- **Background:** `bg-card`, 테두리 `border-border` 한 줄. **그림자 없음.**
- **Internal Padding:** **콘텐츠 카드(`ContentCard`)에는 껍데기가 없다** — 배경·보더·패딩이 전부 0이고 카드는 `flex flex-col gap-2 rounded-xl` 뿐이다(`rounded-xl`은 focus 링 모양용). 그 밖: 16px(목록형 카드) / 32px(인증 카드).
  - **껍데기를 걷은 이유**는 썸네일이 그 화면의 콘텐츠 자체이기 때문이다 — 레퍼런스 둘(크랙·케이브덕)은 카드에 border·padding·배경이 **전혀 없고** 썸네일이 곧 카드다(실측: `padding: 0px`, `rgba(0,0,0,0)`, 썸네일 `rect.left == 카드 rect.left`).
  - **경계는 카드가 아니라 썸네일이 진다**(아래 Thumbnail well). 텍스트는 썸네일 좌측 가장자리와 flush하게 정렬되고 둘 사이는 `gap-2`(8px)다.
  - **hover 신호를 두지 않는다.** 전엔 카드 표면이 `rgb(13,13,13)→(24,24,24)`(대비비 **1.0946**, 픽셀 실측)로 밝아졌는데 칠할 표면이 사라졌고, **레퍼런스 둘 다 카드 hover가 없다** — 케이브덕은 rest/hover 픽셀이 완전 동일하고 DOM에 `hover:`/`group-hover:`/`transition` 클래스가 0개, 크랙도 카드 스타일이 불변이다(1~2초 머물면 미리보기 팝오버가 뜨지만 그건 별개 기능이다). **터치 피드백인 `active:translate-y-px`는 남긴다** — 그게 유일한 눌림 표시다.
  - focus 링(`focus-visible:ring-3 ring-ring/50`)은 카드 전체를 감싼다. 카드에 `overflow-hidden`이 없으므로 잘릴 일도 없다.
- **Hover:** `hover:bg-accent/50` — 사다리 위로 반 칸. **단, 이건 정지 표시용 카드에만 유효하다** — 아래 예외를 볼 것. **`ContentCard`는 hover 자체가 없다**(위).
- **예외: 카드 자체가 그 화면의 주 인터랙션이면 button-outline 레시피를 카드 크기로 쓴다** — `border-border bg-background` + `hover:bg-muted` + 하우스 focus 레시피 + `active:translate-y-px`. `bg-card` 위에서는 `hover:bg-accent/50`도 `hover:bg-muted`도 **픽셀상 아무것도 그리지 않기** 때문이다(`background-color`는 층으로 쌓이지 않고 `bg-card`를 대체한 뒤 페이지 배경 위에 합성된다 — 스크린샷 픽셀 실측 **다크 1.0000:1 / 라이트 1.0178:1**). 이 예외를 쓰면 rest에서 카드 채움이 페이지 배경과 같아져 §4의 명도 사다리를 벗어나지만, 경계는 `border`가 유지하고 hover는 다크 1.0946 / 라이트 1.0902로 실제로 보인다. 대안인 `bg-card` + `hover:bg-secondary`는 라이트에서 `muted-foreground` 본문이 4.30:1로 AA에 미달해 쓸 수 없다 — 셋(사다리·hover 가시성·본문 AA)을 동시에 만족하는 조합은 현재 토큰에 없다. 적용처: `BuilderTypeSelectPage`·`InquiriesPage`·`NoticesPage`·`MyChatRoomListView`. **`ContentCard`는 2026-09-11에 이 레시피에서 빠져나왔다** — 껍데기를 통째로 걷고 hover를 없앴다(위).
- **Thumbnail well:** `overflow-hidden rounded-xl border border-foreground/10 bg-secondary` + 타입별 비율 클래스. **카드의 경계를 이 웰이 진다** — 카드엔 보더가 없다. **네 모서리 모두** `rounded-xl`이다. 이미지 없으면 `ImageOff` 아이콘을 `text-muted-foreground`로.
  - **비율은 콘텐츠 타입이 정한다** — 캐릭터 `aspect-square`(1:1), 스토리 `aspect-story`(2:3, `globals.css`의 `--aspect-story` 토큰). 클래스 매핑은 `entities/content/model/cardLayout.ts`가 단일 소스다(카드와 스켈레톤이 같은 삼항을 각자 들고 있으면 스켈레톤 높이가 어긋난다).
  - **보더가 `border-border`가 아니라 `border-foreground/10`인 이유**: 이제 이미지 **위에** 얹히기 때문이다. `border`(다크 oklch 0.300)는 밝은 이미지 위에서 사실상 안 보이고 어두운 이미지 위에서만 보여 **이미지마다 테두리 유무가 갈린다.** 반투명 흰 선은 어느 이미지 위에서도 가장자리로 읽힌다 — §4의 `ring-1 ring-foreground/10`(떠 있는 팝오버)과 같은 어휘다.
  - **`bg-secondary`인 이유가 바뀌었다** — 전엔 카드의 `hover:bg-muted` 표면과 같은 값이 되는 걸 피하려는 것이었는데, 카드 표면이 사라진 지금은 **페이지 배경(0.160) 위에서 보여야 해서**다(0.260). 썸네일이 아직 없는 초안 카드에서만 보이는 자리다.
  - **`rounded-lg`를 두지 않는다** — 카드의 `rounded-xl`이 `overflow-hidden`으로 썸네일을 직접 자른다. 안쪽에 별도 반경을 두면 border 1px 안쪽 곡률과 어긋난다.
  - **두 비율은 레퍼런스 실측에서 왔다**(2026-09-11): 크랙 캐릭터 표시·원본 **1.000**(400×400, 크롭 0) / 크랙 스토리 표시 0.669·원본 **0.667**(400×600, 크롭 0). 케이브덕은 캐릭터 4:5(0.8)·세계관 **5:4 가로**(1.25)로 갈라 "스토리는 세로"가 업계 합의가 아님을 보여준다 — 크랙 스토리는 웹소설 표지, 케이브덕 세계관은 배경 이미지라서다.
  - **CSS 슬롯은 정확한 2:3이고 생성 치수는 832×1216(=13:19)이다** — 일부러 다르다. 832×1216은 Animagine XL 4.0 권장 버킷이자 NovelAI 기본값이라 학습치 일치를 비율 정확도보다 위에 뒀고, 그 대가로 생성물에서 가로 **2.56%**(832px 중 21.3px)가 잘린다(`card-grid-goal-prompt.md` D-2·D-3). **`bg-muted`가 아닌 이유**: 웰이 `bg-card` 카드 위(rest)에서도, `hover:bg-muted`가 걸린 카드 위(hover)에서도 표면과 같은 값이 되어 사라진다(둘 다 실측 1.0000:1). `secondary`는 두 상태 모두에서 살아남는다(rest 다크 1.2521 / hover 다크 1.1439).
- **Title:** `ContentCard`의 제목은 `line-clamp-2 break-keep break-words`이고 **2줄 높이를 항상 예약한다**(`min-h-[2lh]`, MR-8). 실측(2026-09-14): `text-sm`(16px) 줄높이 **22.857px**, 2줄 클램프 박스(=`min-height`) **45.7031px** — 콘텐츠 길이와 무관하게 항상 이 값이다(`min-height`가 바닥을, 클램프가 천장을 같은 지점에서 막는다 — 297px 분량을 주입해도 45.703125px로 실측). 그 결과 `actions`(32px)가 제목 행 높이를 지배하던 구도가 역전되어(32 < 45.7) `actions` 유무가 제목 행 높이에 영향을 주는 경로가 사라졌고, 로딩 스켈레톤이 nbsp 한 줄로도 정확히 같은 높이를 얻는다. `break-keep`과 `break-words`를 **함께** 쓰는 이유: `break-keep` 단독이면 컨테이너보다 긴 단일 어절이 가로로 넘치고 `line-clamp`은 `text-overflow`를 세팅하지 않아 **`…` 없이 글자 중간에서 하드컷된다**(실측 임계: 390px 스토리 열 111.33px에서 9글자, 제목 실폭 71.33px 열에서 6글자). `MessageBubble.tsx`가 이미 쓰는 하우스 쌍이다.
- **카드 그리드의 열 수는 썸네일 비율이 정한다**(`ContentCardGrid`, `card-grid-techspec.md` T-4): `square` 2/3/4 · `portrait` **3/4/5** · 섞인 목록 2/3/4 + `items-start`. gap은 셋 다 `gap-3`이다. **첫 줄에 `priority`(eager)를 줄 개수도 같은 파일에서 도출한다**(`toPriorityCount`) — 손으로 적은 `index < 4`가 사다리 변경을 따라오지 않아 첫 줄 마지막 카드가 lazy로 빠진 적이 있다.
  - **`portrait`이 390px에서 3열인 것은 껍데기를 걷은 결과다.** 패딩이 있던 동안엔 3열이 불가능했다 — 카드 폭 111.33px에서 `p-3`+border를 빼면 텍스트가 85.3px뿐이라 작가명에 **21.9px(한글 1.8자)** 만 남았다. 껍데기가 사라져 텍스트가 카드 폭 **전체**를 쓰면서 근거가 뒤집혔다. **크랙이 390px 3열을 감당하는 조건이 정확히 이것이었다** — 레퍼런스의 수치를 베낄 때는 그 수치를 성립시키는 조건까지 같은지 볼 것.
  - **지표 숫자는 축약한다**(`formatCompactCount`, `46.8K`·`1.2M`). 3열에서는 조회수 자릿수가 작가명을 그대로 잠식한다 — 전체 숫자면 작가명이 `1,234`에서 3.6자, `46,821`에서 2.9자, `1,234,567`에서 **1.3자**로 줄어든다(390px 3열·작가명 7자 기준 canvas 실측). 축약하면 숫자 폭이 5자 안팎에서 고정돼 자릿수와 무관해진다 — 같은 조건에서 `1.2M`은 **4.0자**, `46.8K`는 3.4자다. **크랙도 같은 이유로 `46K`·`4.7M`을 쓴다.** 상세화면은 폭 제약이 없어 전체 숫자를 유지하고, 스크린리더에는 축약이 아니라 **전체 숫자를 읽힌다**(`sr-only`).
  - **섞인 목록에 `items-start`가 필요한 이유**: 없으면 grid 기본 `stretch`가 짧은 카드를 긴 카드 높이까지 늘려 **빈 border 상자**가 생긴다. 실측(2026-09-14, 390px, `/my` 전체 필터, `actions` 있는 카드): 제목 2줄 예약 전 캐릭터 **267.66px** / 스토리 **354.16px** → 예약 후 캐릭터 **281.37px** / 스토리 **367.87px**(둘 다 +13.70px = 45.7−32, `actions`가 더는 제목 행을 지배하지 않기 때문이다). **절대 차이 86.5px는 전/후 동일하므로 결론(`items-start`가 필요하다)은 바뀌지 않는다.** 이 문서의 이전 값(캐릭터 245 / 스토리 331)은 이번 런 전에 이미 한 줄만큼(약 22.7px) 낮았다 — 원인은 문서화되지 않았다. 예약 후 값(281.37/367.87)은 최종 확정 실측이다. 제목 박스 높이는 콘텐츠 길이·뷰포트와 무관하게 항상 **45.703125px**다(390/768/1512px에서 짧은 제목과 2줄 꽉 찬 제목이 동일). **스켈레톤과 실제 카드의 높이가 같다** — 홈의 스토리 카드(`actions` 없음) 기준 스켈레톤 `offsetHeight` 245px 대 실제 카드 `offsetHeight` 245px, 차이 0(실측). 앞의 281.37/367.87px(`/my` 전체 필터, `actions` 있는 카드)와 값이 다른 것은 모순이 아니다 — 화면·props가 달라서다: 카드 높이는 열 폭과 `actions` 유무에 따라 달라진다. **한 행의 카드들 조회수 줄 `top`이 정렬된다**(Δ ≤ 0.008px, 서브픽셀 반올림뿐). **잘림 건수 실측**: 시드 스토리 제목 30건 중 390px **24** · 640px **6** · 768px **8** · 1024px **0**(현행 1줄에서는 390/640/768 전부 30건이었다) — 예측과 정확히 일치했다. `min-h-[2lh]`의 computed `min-height`가 **45.7031px**임을 확인했다(`lh` 단위가 동작한다).
- **Empty state:** `rounded-xl border border-dashed border-border py-16` — 점선은 빈 상태와 컬러 피커에만 쓴다.

### Inputs / Fields
- **Style:** radius `lg`(8px, §반경 정책 — `Input`은 36px 티어), `border-input` 테두리, 투명 배경. **이 테두리는 장식이 아니라 컨트롤 식별자다** — 채움이 배경과 같아 이 한 줄이 없으면 필드가 존재하지 않는다. 값은 §2 Neutral의 `input`(구분선 `border`와 다른 값)이고 3:1을 진다.
- **Focus:** `ring-3 ring-ring/50` + `border-ring` — 버튼과 동일한 포커스 언어.
- **Error:** `aria-invalid`에 `border-destructive` + `ring-destructive/20`. 에러 텍스트는 Label 크기 + `text-destructive-text`(글자는 텍스트 전용 토큰, 보더·링은 `--destructive`).

### Menus / Popover lists (드롭다운 · 셀렉트 · 자동완성)
- **포커스 표시는 채움이 아니라 링이 진다** — `focus:inset-ring-1 focus:inset-ring-ring`, `bg-accent`는 보조로 남긴다. 채움만으로는 못 고친다: 포커스 배경(`accent`)이 팝오버 표면 대비 **1.1439 다크 / 1.1239 라이트**(destructive 항목은 `bg-destructive/10`이라 1.1119 / 1.1598)이고, **사다리 최상단 `border`를 채움으로 써도 약 1.3**이다. 링은 팝오버 대비 **6.5567 / 6.1465**, 포커스 채움 대비 중립 **5.7320 / 5.4691** · destructive **5.8968 / 5.2997**이다.
- **링 색은 variant별로 가르지 않는다** — 하나(`ring`)로 중립·destructive 둘 다 3:1을 넘기므로, 한 메뉴 안에서 포커스 어휘가 갈릴 이유가 없다. 심각도는 링이 아니라 글자·글리프 색(`destructive-text`)이 진다.
- **이 규칙은 팝오버 리스트 전체에 건다** — `DropdownMenuItem`(default·destructive)·`CheckboxItem`·`RadioItem`·`SubTrigger`·`SelectItem`, 그리고 손으로 만든 옵션 리스트(채팅 단축어 자동완성). 한 곳만 고치면 같은 모양의 목록에서 포커스 표시가 갈린다.
- **`outline-hidden`을 쓴 리스트를 새로 만들면 링을 함께 넣는다.** 그 유틸리티가 UA 아웃라인을 지우므로, 넣지 않으면 남는 신호가 1.1:1짜리 배경 변화 하나뿐이다.
- **비활성 항목은 `opacity-65`다**(상류 shadcn은 `opacity-50`). 50%면 항목 글자가 팝오버 위에서 **3.2515 라이트 / 4.4959 다크**로 AA 아래고, 이 앱은 "왜 못 누르는지"를 읽혀야 하는 비활성 항목이 있다. 65%면 **5.1882 / 6.7086**이다. Radix가 비활성 항목을 키보드 이동에서 건너뛰고 `pointer-events: none`이라 링은 그려지지 않는다(실측).

### Navigation
- **크롬은 sticky 헤더 하나뿐이다.** `sticky top-0 z-30 h-14 border-b border-border bg-background`, 내부 바는 **full-bleed다**(`mx-auto max-w-5xl` 없음, `px-4 sm:px-6`만 유지 — MR-1, `main-refact-goal-prompt.md`). 본문은 `max-w-5xl`을 그대로 유지하므로 **로고 left와 `<main>` 콘텐츠 left는 이제 의도적으로 어긋난다**: 전역 헤더는 뷰포트에 속하고 본문은 컬럼에 속한다는 쪽을 택했다. **이건 뒤집은 결정이다** — 한때는 "헤더 폭 자체엔 근거가 없었지만 본문 max-width엔 있으니(§Layout containers의 잉크 폭 실측) 근거 있는 쪽(본문)에 맞춰 정렬한다"였고, 그 결정이 유효했던 동안의 실측은 1440px에서 헤더 로고 left와 `<main>` 콘텐츠 박스 left가 둘 다 224.5px, drift 0.00이었다 — **단 이 224.5px는 스크롤바를 중화하지 않고 잰 값이다**: 1440px이면 산수상 232px가 나와야 하는데, 실제 레이아웃 폭이 스크롤바만큼 줄어든 1425px이었다((1425−1024)/2 + 24 = 224.5) — 즉 그 "1440px 실측"은 실제로는 1425px 실측이었다. 폭을 재기 전 스크롤바를 중화해야 하는 이유의 실례다. full-bleed 후 실측: **drift = −(뷰포트 − 1024) / 2** — `max-w-5xl`(1024px)이 센터링을 발동시키는 순간부터 로고 left와 `<main>` 콘텐츠 left가 벌어진다. 1024px 이하에서는 로고와 본문 콘텐츠가 둘 다 패딩 경계(16/24px)에 앉아 drift 0이다. 콘텐츠 박스 기준 실측: 390px 16/16 → 0 · 1024px 24/24 → 0 · 1440px 24/232 → −208 · 1512px 24/268 → −244 — **1024px를 넘는 순간부터 벌어지며, 가장 큰 뷰포트에서만 갈리는 게 아니다.** `px-4 sm:px-6`을 그대로 유지하는 이유: 헤더를 `px-6`으로 올리면 390px에서 헤더 내부 폭이 358→342px로 줄어 검색 펼침 + 아이콘 4개의 압박 지점에 들어간다(§Layout containers에 이미 있는 실측). 하단 탭바·사이드 레일·푸터는 **존재하지 않으며, 추가하지 않는다** — 크롬은 얇고 항상 동일해야 한다.
- **이 금지의 대상은 전역 크롬이다 — `<main>` 안에서 한 라우트의 콘텐츠를 여러 열로 나누는 것은 이 Don't의 대상이 아니다**(`BuilderLayout`의 lg 2단, `/studio/images`의 lg 3단). **금지의 본질은 정지 상태의 크롬이 항상 두 줄 이상 보이는 것이다.** 판별 기준은 폭이 아니라 둘이다 — ① 모든 라우트에 상시 존재하는가 ② `h-14` 밖에 크롬 줄을 더하는가. 둘 중 하나라도 참이면 사이드 레일이고, 둘 다 거짓이면 페이지 콘텐츠다. **"역할이 화면 전환인가"는 더 이상 단독 판정 기준이 아니다**(MR-13, 이 조항의 두 번째 개정 — 첫 번째는 이미지 페이지 3열, `image-refact-goal-prompt.md` IR-1) — 버거로 여는 **일시적** 패널은 화면 전환용 목적지 목록을 담아도 정지 상태의 크롬을 늘리지 않으므로 예외다(좌측 드로어, MR-9·MR-10, 아래 — ①거짓 ②거짓이라 사이드 레일이 아니다). **예외를 목록으로 늘리는 대신 축을 고친 이유**: 예외가 셋이 되면 원칙보다 예외 목록이 규칙이 된다. 이 레이아웃은 사이드 레일이 아니다 — 그 라우트에만 있어 상시 존재하지 않고(①거짓), 크롬은 여전히 위 `h-14` 헤더 하나뿐이다(②거짓 — 열 사이 전환도 화면 전환이 아니라 같은 화면 안의 배치다). `/studio/images`의 좌열(보관함)·우열(생성 옵션)도 같은 두 축으로 사이드 레일이 아니다 — 그 라우트에만 있고, lg 미만에서는 탭 스트립의 아이콘 버튼으로 여는 바텀시트로 접힌다(같은 화면의 다른 표현일 뿐 화면 전환이 아니다). 아래 채팅 더보기 패널도 같은 두 축으로 사이드 레일이 아니라고 판정된 선례다. **이 예외는 `<main>` 내부의 다열 레이아웃과 버거로 여는 일시적 패널에 한정되며 전역 셸로 번지지 않는다** — 새 전역 사이드바나 상시 내비게이션 레일을 추가할 근거로 쓰지 말 것. 크롬은 여전히 `h-14` 헤더 하나뿐이다.
- **예외는 빌더 라우트다** — `/builder`(타입 선택)·`/builder/$type/$draftId` 둘 다 전역 헤더를 렌더하지 않는다(`routes/__root.tsx`가 pathname이 `/builder`로 시작하면 `<Header/>`를 건너뛴다). 대신 같은 56px 자리에 전용 상단바(`features/build-common`의 `BuilderTopBar`)가 들어가므로 **크롬은 여전히 한 줄**이고, 아래 `calc(100dvh-3.5rem)`류 높이 계산도 그대로 유지된다(크랙 실측 상단바가 마침 56px로 같았던 것을 활용했다). 상단바는 뒤로가기(항상 `/my`)·제목(h1)·액션 버튼(미리보기/임시저장/발행)·자동저장 안내문 넷을 한 행에 담는다 — 타입 선택 화면은 폼이 없어 액션·안내문 없이 뒤로가기·제목만 쓴다. 390px 미만에서는 이 절의 라벨 숨김 선례(`hidden sm:inline`)를 그대로 따라 액션 버튼이 아이콘만 남는다(`aria-label`은 유지).
- **이 규칙은 `apps/web` 전용이다. `apps/admin`은 예외로 좌측 사이드바를 쓴다**(D-9, `widgets/admin-sidebar`). web은 콘텐츠 몰입이 전제라 크롬이 얇고 고정돼야 하지만, admin은 화면 전환 자체가 주 동작인 운영 콘솔이라 사이드바가 맞는 크롬이다 — "불 꺼진 방" 북극성이 애초에 admin에는 적용되지 않는다(admin은 라이트 고정, §1).
- **워드마크는 아이콘 없는 타이포그래픽 마크 하나다**(`또나`, `text-lg font-bold tracking-tight text-foreground`). 파비콘(Pretendard Bold `또` 글리프)·OG 이미지(`또나` 워드마크)와 같은 계보이며, 로고에 심볼 아이콘을 붙이지 않는다 — 마크가 둘이면 브랜드가 둘이다. 색도 없다: 로고는 강조 지점이 아니므로 `primary`가 아니라 `foreground`다(§2 One-Accent Rule).
- **모바일 대응은 라벨 숨김과 레이아웃 분기 둘 다 쓴다**(MR-9·MR-13, 2026-09-14 개정 — 한때 "레이아웃 분기가 아니라 라벨 숨김이다"라고 적혀 있었으나 헤더 자체가 뷰포트별로 갈리는 지금은 거짓이다). 라벨 숨김은 빌더 상단바의 액션 버튼에 남는다(`hidden sm:inline`). **헤더는 경계 `sm`(640px)에서 두 구성으로 갈린다**(MR-9):
  - **`sm` 미만**: [버거 왼쪽] · [워드마크 중앙] · [검색 오른쪽] 셋뿐이다. 콘텐츠 유형 토글·이미지 생성·알림·프로필(비로그인은 로그인)은 좌측 드로어로 들어간다(아래).
  - **`sm` 이상**: 로고 좌측 · 텍스트 탭 · `ml-auto` 아이콘 그룹(현행 유지).

  **구현은 한 DOM에 `grid grid-cols-[1fr_auto_1fr] … sm:flex`를 쓴다** — 마크업을 두 벌 두지 않는다(로고가 둘이면 접근가능한 홈 링크가 둘이고, 검색을 두 벌 마운트하면 상태가 갈린다). `display:none` 자식은 grid 아이템을 만들지 않으므로 모바일에서 버거=1열·로고=2열·우측=3열이 되고, `1fr auto 1fr`이라 버거와 검색의 폭이 달라도 로고가 정확히 중앙이다. `sm:flex`에서는 `grid-template-columns`가 무효라 되돌리는 클래스가 필요 없다.

  **헤더의 캐릭터/스토리 토글은 여전히 라벨 숨김의 대상에서 빠진다**(MR-2, 2026-09-14) — 아이콘이 없고 라벨을 항상 보이는 텍스트 탭이다. 토글 그룹 폭은 108.00 → **126.97px**(구현된 `px-2` 기준, MR-2a)로 커진다. **근거는 320px 넘침 방지가 아니다** — 그 압박은 토글이 `sm` 미만 헤더에서 아예 빠지면서(MR-9) 해소됐다(그 넘침 실측 자체는 버리지 않는다 — "토글이 모바일 헤더에 있던 동안의 값"으로 아래 §Toggles가 남긴다). `px-2`는 **텍스트 탭이 채움이 없어 알약 패딩이 필요하지 않기 때문**이다 — 패딩은 모양이 아니라 히트 영역만 정하고, `h-9`(36px)가 유지되므로 WCAG 2.5.8(24×24)을 그대로 만족한다. 폭 감소는 부수 효과일 뿐이다.

  **워드마크는 두 구성 모두에서 항상 노출된다**(모바일에서는 중앙) — 2자(≈36px)라 숨겨서 아낄 폭이 없고, 숨기면 홈 링크에 접근 가능한 이름이 남지 않는다.

  검색은 `w-8`에서 `w-40 sm:w-64`로 펼쳐진다 — 다만 이 값은 선호 폭이지 하한이 아니다. **`sm` 미만에서 검색을 펼치면 헤더를 독점한다**(MR-12) — 버거·로고를 숨기고 한 줄 전체가 입력칸이 된다(좌측에 닫기 버튼). 분기는 CSS로 한다 — `Sheet`와 달리 in-flow 요소라 `sm:` 클래스가 닿는다(JS 분기가 필요 없다). `sm` 이상의 인라인 펼침은 그대로다 — 우측 아이콘 그룹과 펼친 검색은 `min-w-0`을 갖고 있어, 폭이 모자라면(390px에서 아이콘 4개 + 펼친 검색) 아이콘(`shrink-0`)이 아니라 검색만 줄어든다.

  **헤더 폭 예산 실측 지침도 뷰포트별로 갈린다**(MR-9 이후) — `sm` 이상에서 아이콘을 더 추가할 땐 이 상태에서 `bar.scrollWidth === bar.clientWidth`를 실측할 것(모바일 항목이 셋뿐이라 압박 지점이 `sm` 이상으로 옮겨간다). **`sm` 미만에 아이콘을 더하려면 드로어에 넣는 것이 기본이다** — 항목이 셋뿐인 구성에 넷째를 얹는 건 예외로 다룬다.

  **아직 코드가 없는 자리** — 위 두 구성의 정확한 측정값(버거 left, 로고 중앙 오차, 320·390 넘침 등)은 여기 적지 않는다. 실측은 `main-refact-progress.md`의 V-1a·V-1b에서 채운다.
- **좌측 드로어**(`Sheet side="left"`)가 `sm` 미만 헤더에서 숨긴 항목 전부를 담는다(MR-10) — `packages/ui/src/components/sheet.tsx`가 `inset-y-0 left-0 h-full w-3/4 border-r` + `sm:max-w-sm` + 내장 닫기 버튼을 이미 갖고 있다. **이 저장소의 첫 좌측 시트다** — 기존 3곳(아래 채팅 더보기 드롭업 등)은 전부 `side="bottom"`이다. 내용은 **평면 목록**이다: 유형 전환(가로 pill 쌍, 아래 §Toggles) / 구분선 / 이미지 생성 · 알림 / (로그인 시) 프로필 하위 항목 전부 펼침, 비로그인은 로그인 하나. **`ProfileMenu`를 드로어에 그대로 넣지 않는다** — 시트 안에서 Radix 드롭다운을 다시 여는 중첩이고, `apps/web/CLAUDE.md` §메뉴·모달이 이미 "열린 Sheet는 포커스 트랩과 바깥 클릭 차단까지 걸어 인라인 패널과 공존할 수 없다 — 둘 중 하나만 마운트되어야 한다"고 적어 뒀다. 목적지 목록은 **한 곳에서만** 정한다(`ProfileMenu`가 쓰는 것과 같은 소스) — 안 그러면 한쪽에만 항목이 추가되는 실패 모드다(`toContentStatusTags` 선례). **트리거는 드로어 위젯이 소유한다**(자기완결 위젯) — 호출부(`Header`)는 컴포넌트 하나만 배치하고 열림 상태를 알지 않는다.
- **미확인 알림은 버거에 점으로 승격한다**(MR-11) — 개수가 아니라 점이다(버거는 여러 항목의 수납구라 숫자를 달면 무엇의 개수인지 모호해진다), 색은 `primary`. 모바일 헤더에는 텍스트 탭도 장르 칩도 없어 이 점 하나가 `primary` 솔리드 채움의 유일한 자리다(§2 밝기 예산 규칙).
  **아직 코드가 없다** — 드로어 레이아웃 수치·포커스 복원·알림 점 노출 조건은 `main-refact-progress.md`의 V-17~V-21에서 채운다.
- **채팅 화면은 뷰포트 고정이다**: `h-[calc(100dvh-3.5rem)]`. 이 `3.5rem`은 헤더의 `h-14`를 수동으로 미러링한 값이므로 **헤더 높이를 바꾸면 7곳을 함께 고쳐야 한다**(`ChatRoomView` 3 · `PreviewSessionView` · `BuilderLayout` · `BuilderPreview` · `ImageStudioShell`). 2026-09-11 재측정 — 그 전까지 이 줄은 "5곳"이라 적혀 `BuilderPreview`를 빠뜨리고 있었다. **2026-09-14 재측정 — "6곳"도 틀렸다**, `ImageStudioShell.tsx:90`이 빠져 있었다(`main-refact-goal-prompt.md` I-2).
- **채팅 더보기 패널은 1024px 이상에서 인라인 사이드바다**(`w-72`, `border-l border-border`, `bg-card`, 채팅 헤더 아래부터 바닥까지). 이것은 사이드 레일이 아니다 — 기본이 닫힘이고 채팅 라우트에만 있으며 ⋮로 여는 일시적 패널이다(크롬은 여전히 `h-14` 헤더 하나뿐이다). 오버레이가 아니라 채팅 컬럼과 폭을 나눠 갖는 이유는 **열어둔 채로 대화를 계속 읽고 보낼 수 있어야** 하기 때문이다. 분기는 `lg:` 클래스가 아니라 JS(`useMedia`)로 한다 — `Sheet`는 body로 포털돼 부모 클래스가 닿지 않고, 열린 `Sheet`는 포커스 트랩까지 걸어 인라인 패널과 공존할 수 없다.
- **1024px 미만에서 같은 패널은 바닥에서 올라오는 드롭업이다**(`Sheet side="bottom"` + `top-[118px]` + `rounded-t-xl`). 우측 시트가 아니라 드롭업인 이유는 **누구와 대화 중인지가 계속 보여야** 하기 때문이다 — 시트 상단을 채팅 헤더 바로 아래에 붙여 아바타·캐릭터명·방 이름을 남긴다. 그 `118px`는 전역 헤더 `h-14`(56) + border 1 + 채팅 헤더 60 + border 1을 실측한 값으로, 위의 `calc(100dvh-3.5rem)`와 같은 계열의 수동 미러링이다(헤더 높이를 바꾸면 여기도 함께 고친다). 전역 헤더는 채팅 헤더 위에 있으므로 함께 남는다 — 둘을 따로 고를 수 없다. 오버레이 스크림은 그 위를 덮으므로 헤더는 보이되 흐려진다(의도된 모달 표현).

### Status badges
- **Shape:** `inline-flex items-center rounded-full px-2 py-0.5 text-badge font-medium`. 전용 `Badge` 프리미티브는 없고 각 자리에서 손으로 조립한다(크기만 토큰이다 — §Typography의 Badge 티어).
- **중립 상태(공개/링크공개/비공개/미등록, 문의 대기/답변완료):** `border border-border` — **채움이 아니라 윤곽이다**. `bg-muted` 채움은 카드 표면과 같은 값이 되는 순간이 반드시 있어(정지 `bg-card` 카드 위에서, 또는 `hover:bg-muted`가 걸린 카드의 hover에서 — 둘 다 실측 1.0000:1) 알약이 통째로 사라진다. 윤곽은 hover에서도 살아남는다(다크 1.3076 / 라이트 1.2699). 결과적으로 **타입=채움 / 상태=윤곽**으로 형태가 갈려 위계가 생긴다.
- ⚠️ **프론트매터의 `badge-status`는 이 사실을 온전히 표현하지 못한다**(2026-09-11, backlog B-21). 한때 `backgroundColor: "{colors.muted}"`로 적혀 있어 **실제 구현과 정면으로 달랐고**(실제는 채움 없는 윤곽), 지금은 `"transparent"`로 고쳤다. 다만 그 스키마에 `borderColor` 슬롯이 없어 **윤곽 자체는 여전히 적을 수 없다** — 이 절의 산문이 단일 진실이다. 프론트매터만 보고 배지를 재현하지 말 것.
- **중립 상태 안의 위계는 잉크 명도로 만든다.** 기본은 `text-muted-foreground`, **사용자가 읽을 게 생긴 상태만** 밝기 천장 `text-foreground`로 올린다 — 지금은 문의의 `답변완료` 하나뿐이다(`entities/inquiry/model/inquiryStatus.ts`의 `INQUIRY_STATUS_BADGE_INK`). 색으로 가르지 않는 것은 PRODUCT.md가 "UI 자체(배경/텍스트/버튼/배지)는 무채색"으로 못박았기 때문이고, 이 시스템의 깊이는 원래 명도 사다리가 만든다.
  - **`hover:bg-muted` 카드 위가 최악이고, 라이트의 `대기`가 AA 경계에 가장 가깝다**(스크린샷 픽셀 디코드 실측, `/ui-demo`): `대기` 다크 6.7374→**6.1553**, 라이트 5.2511→**4.8165**(AA 여유 0.32뿐 — hover 표면을 더 어둡게 하거나 `muted-foreground`를 더 밝히면 깨진다). `답변완료`는 다크 15.8622→14.4917, 라이트 17.2244→15.7988로 여유가 크다. 윤곽 자체는 다크 1.4312→1.3076, 라이트 1.3845→1.2699다.
- **이용제한:** `bg-destructive/10 text-destructive-text` — 틴트, 채움 아님.
- **타입(캐릭터/스토리):** `bg-secondary text-secondary-foreground` + 14px 아이콘.
- **삭제:** 배지가 아니라 전체 패널 빈 상태로 표현한다(`ContentUnavailableState`) — 아이콘 + 제목 + 설명.
- 상태 배지는 소유자에게만 렌더한다.

### Layout containers
페이지 컨테이너의 표준 관용구는 `mx-auto flex max-w-* flex-col gap-* px-4 sm:px-6 py-10`이다. **헤더 쪽 값(`px-4 sm:px-6`)에 맞춘 이유**: 반대로 헤더를 `px-6`으로 올리면 390px에서 헤더 내부 폭이 358→342px로 줄어 §Navigation이 경고한 압박 지점(검색 펼침 + 아이콘 4개)에 들어간다 — 본문을 내리는 쪽은 그 위험이 없다(실측: 390px·320px 둘 다 검색 펼친 상태에서 헤더 바 `scrollWidth === clientWidth`, 넘침 0). max-width는 콘텐츠 밀도에 따라 고른다: 그리드형 목록 `max-w-5xl`, 프로필 `max-w-4xl`, 폼·상세·대화방 목록(`/chats`, `widgets/chat-room-list`) `max-w-2xl`, **설정(`/mypage`) `max-w-md`**. **빌더는 lg 미만 `max-w-2xl`, lg 이상 `max-w-7xl` 2단(폼 열은 `max-w-2xl` 유지)이다.** 빌더 라우트에는 전역 헤더가 없다(§Navigation 빌더 예외) — 대신 상단바(`BuilderTopBar`)도 전역 헤더와 같은 규칙대로 **full-bleed다**(MR-3, `main-refact-goal-prompt.md`) — max-width를 걷었다. `features/build-common/lib/builderMainMaxWidth.ts`의 `builderMainMaxWidth(isPreviewOpen)`은 이제 `BuilderLayout`의 `main`(본문) **전용 함수**다. **한때는 이 문장이 "같은 `mx-auto max-w-7xl px-4 sm:px-6` 컨테이너를 쓴다"고 적혀 있었는데 근거가 틀렸다** — 실제로는 상단바가 브레이크포인트 접두사 없는 `max-w-7xl` 고정이었고 `main`은 `lg:max-w-7xl` + (`!isPreviewOpen`일 때만) 접두사 없는 `max-w-2xl`이라 서로 다른 식이었다. `max-w-7xl`(1280px)이 lg 미만 뷰포트보다 항상 커서 상단바가 사실상 무제한으로 넓어지는 구간에서 두 식이 갈렸다 — `main`이 `max-w-2xl`(672px)로 좁아지는 672~1023px에서 drift가 74px(820px)~175.5px(1023px)까지 선형으로 벌어졌고, 1440px 한 지점에서만 두 식이 우연히 같은 값(1280px)을 줘 그 폭만 잰 실측이 drift 0으로 나왔다(builder-preview-validation 회귀). 그 회귀를 고치려고 한동안 상단바·본문이 **같은 함수**를 호출해 값이 아니라 **식 자체**를 같게 만들었지만, 상단바가 full-bleed가 된 지금은 **비교할 축 자체가 사라졌다** — "두 식이 같은가"라는 질문이 되돌아간 게 아니라 성립하지 않게 된 것이다. 그 대가로 **뒤로가기 버튼 left와 폼 열 left의 drift 0을 포기한다.** 화면별 drift(뒤로가기 버튼 left 대비 폼 열/콘텐츠 left, 상단바 full-bleed 후 실측): **`/builder` 타입 선택** 390px **0** · 1024px **−176** · 1440px **−384** — 이 화면은 **`BuilderLayout`을 쓰지 않고** `<main>`이 `mx-auto max-w-2xl`(672px)로 가운데 정렬되어 1440px에서 콘텐츠가 408px에서 시작하기 때문에 크게 벌어진다. **실제 빌더**(`/builder/$type/$draftId`) 390px **0** · 1024px **0** · 1440px **−80** — `BuilderLayout`이 그리드를 `main`에 두고 padding을 폼 열 div에 둬서 1024px까지 drift 0이 유지된다. **프리뷰를 열고 닫아도 상단바가 움직이지 않는다**(390px 세 상태 모두 뒤로가기 left 16 · 상단바 폭 390 실측) — 상단바가 `isPreviewOpen`을 더는 받지 않기 때문이다. 식이 같던 동안의 실측(뒤로가기 버튼 `left` vs 폼 열 콘텐츠/탭 목록 `left`, `isPreviewOpen=false`): 390px 16/16, 672px 24/24, 820px 98/98, 1023px 199.5/199.5, 1024px 24/24, 1440px 104/104(전 구간 drift 0), `BuilderTypeSelectPage`(390·820·1440px)와 스켈레톤/에러 상태(390·820px)도 동일 — **이 값들은 상단바가 `max-w-7xl`을 함께 쓰던 동안의 값으로 남긴다.** 조사로 드러난 사실: `BuilderTopBar`를 렌더하는 5곳 중 **3곳(`BuilderTypeSelectPage`, `BuilderPage`의 에러·스켈레톤 상태)은 애초에 `BuilderLayout`을 쓰지 않고 본문이 `max-w-2xl` 리터럴을 직접 가진다** — 즉 "상단바와 본문이 같은 함수를 호출해 식이 같다"는 서술은 그 3곳에서는 **원래도 참이 아니었고**, 상단바만 함수를 호출했고 본문은 우연히 같은 값을 내는 리터럴이었다(`builderMainMaxWidth.ts` 자신의 docstring이 이미 그 구분을 인지하고 있었다). 나머지 두 곳(`StoryBuilderShell`·`CharacterBuilderShell`)만 `BuilderLayout`을 통해 실제로 그 함수를 호출했다. **대화방(`/chat/$roomId`)도 다른 라우트와 같은 `max-w-5xl` 컬럼에 산다** — 근거는 로고 정렬이 아니라 **본문 컬럼 규약**이다(그리드형 목록과 같은 폭, 위 표준 관용구). 전역 헤더 내부 바가 full-bleed(MR-1)가 되면서 로고 x는 더 이상 비교 대상이 아니다. 한때 full-bleed였고 그게 의도라고 여기 적혀 있었지만 틀렸다 — 패딩만 헤더와 맞춰 두면 `padding-left`는 24px로 같아도 콘텐츠 x는 어긋난 채고, 헤더가 `max-w-6xl`에서 `max-w-5xl`로 내려오면서 로고가 오른쪽으로 64px 밀려 그 격차가 **144.5px → 200.5px로 넓어졌다**(1425px 실측). **컬럼 제한은 셸 바깥이 아니라 채팅 컬럼과 사이드바를 담는 flex 행에 건다**(`mx-auto flex w-full min-h-0 max-w-5xl flex-1`). 이렇게 해야 더보기 사이드바(`ChatMoreSidebar`)가 오버레이가 되지 않고 채팅 컬럼과 폭을 나눠 갖는 in-flow `<aside>`로 남으면서(열어둔 채로 입력해야 해서 포털+모달 전제인 Sheet를 쓸 수 없다, §Navigation) 채팅 컬럼이 그 행의 **첫** flex 아이템이라 사이드바를 여닫아도 좌측 콘텐츠 시작점이 움직이지 않는다 — 폭은 오른쪽에서만 줄어든다. **`w-full`을 빼면 안 된다**: flex 컬럼의 자식에 `margin-inline: auto`가 붙으면 명세상 stretch가 꺼져 폭이 shrink-to-fit으로 붕괴한다(1200px 부모에서 8.2px vs 1024px, 실측). 실측(1425px, **헤더 내부 바가 `max-w-5xl`이던 동안의 값**): 로고 x와 채팅 헤더·메시지 영역·입력창의 콘텐츠 x가 모두 **224.5px, drift 0.00**이었고 사이드바 개폐 4회 × 50프레임 동안 문서 넘침 0이었다. 1265·1024·753·390px에서도 drift 0.00, `lg` 경계(1024)에서 사이드바 288px / 메시지 컬럼 736px였다. **뷰포트를 가로지르는 선은 전역 헤더의 `border-b` 하나뿐이다** — 채팅 헤더의 `border-b`는 `<header>`가 아니라 안쪽 컬럼 div에 걸어 선이 뷰포트가 아니라 컬럼 경계를 따르게 한다(1425px 실측: 전역 헤더 1425 / 채팅 헤더 1024 / 입력창 1024px). **전역 헤더가 full-bleed(MR-1)가 된 뒤에도 이 문장은 그대로 참이다** — 그 선은 애초에 내부 바가 아니라 `<header>` 태그 자체에 걸려 있어 내부 바가 좁았을 때도 이미 전폭이었다. **단 아래 선들과 길이가 같아지는 건 사이드바가 닫혀 있을 때뿐이다** — 열면 채팅 헤더 선은 행 전체(1024px), `StatGaugePanel`·버전 배너·입력창의 선은 채팅 컬럼만(736px) 덮는다. 헤더가 채팅 컬럼과 사이드바 둘 다의 위에 있으므로 이게 맞는 동작이다(옮기기 전 같은 상태는 1425 vs 736이었다). 빌더 미리보기(`PreviewSessionView`)도 같은 셸이라 같은 규칙을 따른다(사이드바가 없어 행 대신 `flex-col` 래퍼다). 인증 화면만 다른 셸을 쓴다(`min-h-screen items-center justify-center px-4 py-12` + `sm:max-w-sm` 카드) — **여기는 손댈 것이 없다**: 패딩이 실제로 닿는 구간은 뷰포트 480px 이하뿐이고(448 + 32), 그 구간은 전부 `sm:` 미만이라 새 통일값과 이미 16px로 같다. 480px 초과에서는 카드가 중앙 정렬돼 패딩이 관여하지 않는다(실측: `sm` 미만에서 `/login`·`/signup`도 다른 라우트와 drift 0.00). **인증 화면에 브랜드 마크를 따로 두지 않는다** — 전역 헤더가 인증 라우트에도 마운트되므로(빌더 라우트만 예외, §Navigation) 카드 위에 워드마크를 얹으면 같은 단어가 한 화면에 두 번 나온다.

**컬럼은 그 안에서 가장 넓은 *고대비 잉크*에 맞춘다 — 가장 넓은 컨트롤이 아니다.** 이 시스템에는 카드도 보더도 사이드 레일도 없어 컨테이너 경계가 화면에 그려지지 않는다. 그래서 사용자가 중심을 판정하는 기준은 박스가 아니라 **텍스트**다. `w-full` 컨트롤(인풋·폼)은 컬럼이 얼마나 넓든 컬럼을 채우므로 폭 선택의 근거가 되지 못한다 — **항진명제**이기 때문이다(`/mypage` 비밀번호 인풋은 `max-w-md`에서 400px, `max-w-2xl`에서 624px로 **양쪽 다 콘텐츠 박스를 정확히 채운다**). 근거는 텍스트 쪽인데, 이유는 잉크 폭이 고정이어서가 아니라 **컬럼만큼 빨리 늘지 않아서**다 — 산문은 늘어난 폭을 줄바꿈으로 흡수하고 마지막 줄이 오른쪽에 빈자리를 남긴다. `/mypage`는 콘텐츠 박스를 400→624px(+224)로 늘려도 잉크가 391.13→450.11px(+59)까지만 늘고, 남는 폭이 전부 오른쪽에 쌓여 잉크 중심이 왼쪽으로 밀린다 — 뷰포트 중심 대비 `max-w-md` **−4.44px**, `max-w-2xl` **−86.95px**(1280px A/B 실측). **박스 자체는 두 폭 모두 정확히 중앙이다(drift 0)** — 그런데 그 박스를 그리는 유일한 선인 인풋 보더가 저대비라 눈에 남는 건 텍스트뿐이다. 목록에서 가장 넓은 항목이 사라지면 컬럼도 함께 줄인다.

**간격은 gap 하나로만 만든다** — `space-y-*`와 `divide-*`는 앱 전체에서 **0회** 사용이며, 레이아웃은 100% `flex flex-col gap-*`이다. 가장 많이 쓰이는 값은 `gap-1.5`(6px, 라벨↔인풋)와 `gap-2`(8px, 버튼 행)다.

**Tailwind 브레이크포인트는 `sm`(640px)과 `md`(768px) 둘뿐이었다.** `lg:`(1024px) 클래스는 **빌더 2단 레이아웃 4개 파일과 상세화면 하단 고정 CTA 2개 파일에만 있다**. 빌더 넷은 앱 최초의 `lg:` 도입이다: 2단 그리드 분기 자체를 쥔 `features/build-common/ui/BuilderLayout.tsx`, 폼 열·상단바 max-width를 프리뷰 열림 여부로 가르는 `features/build-common/lib/builderMainMaxWidth.ts`(`lg:max-w-7xl`), 그리고 lg 이상에서 필요 없어지는 모바일 전용 [미리보기]/닫기 버튼을 `lg:hidden`으로 숨기는 `features/build-common/ui/BuilderTopBarActions.tsx`·`widgets/builder-preview/ui/PreviewCloseHeader.tsx`. 상세화면 둘은 플레이 CTA를 lg 미만에서만 하단 고정으로 띄우는 `pages/content-detail/ui/ContentDetailPage.tsx`(`lg:pb-10`)와 `widgets/content-detail/ui/ContentDetailView.tsx`다(D-7/D-11/D-12). 콘텐츠 그리드가 `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`에서 멈추는 것은 여전히 의도다. 채팅 더보기 패널의 1024px 분기(§Navigation)는 CSS가 아니라 JS 미디어쿼리인데, `Sheet`가 body로 포털돼 부모의 `lg:` 클래스가 닿지 않고 열린 `Sheet`가 포커스 트랩까지 걸어 인라인 패널과 공존할 수 없기 때문이다 — 빌더 프리뷰 열은 포털 없는 in-flow 요소라 그 제약이 없어 CSS `lg:`로 분기한다.

### Motion
- **모션 라이브러리는 없다.** `tw-animate-css` + Tailwind 유틸리티만 쓴다. 이 시스템에 코레오그래피는 존재하지 않는다.
- **지속시간은 100-300ms**: 팝오버 100ms, 스텝 전환·검색 확장 200ms, 스탯 게이지 300ms. `ease-out`.
- **모든 모션은 `motion-safe:` 접두사로 가드한다** — 어두운 방에서 갑작스러운 움직임은 놀람이다. 새 애니메이션을 추가할 때 `motion-safe:`를 빼먹지 말 것. `packages/ui`의 프리미티브 12개는 US-005에서 전수 게이팅됐고(dialog·alert-dialog·sheet·dropdown-menu·select·button·toggle·switch·tabs·input·textarea·checkbox·table), `reduce`에서 `animation-name: none` · `transition-duration: 0s`가 되는 것이 실측돼 있다.
  - **`duration-*`도 함께 가드한다.** `duration-100`은 `transition-duration`까지 세팅하는데 CSS의 `transition-property` 초깃값이 `all`이라, 애니메이션만 끄면 `reduce`에서 `transition: all 0.1s`가 살아남는다.
  - **호출부에서는 못 끈다** — `motion-reduce:animate-none`을 얹어도 `data-open:` 변형의 속성 선택자가 특이도에서 이긴다. 프리미티브에서 가드하는 것 말고 방법이 없다.
  - **예외는 진행 표시다** — 로딩 스피너(`animate-spin`)·스켈레톤(`animate-pulse`)·**타이핑 인디케이터**(`animate-pulse`)는 멈추면 "멈춘 UI"로 읽히므로 가드하지 않는다. 장식·전환은 가드하고 진행 표시는 남긴다. **타이핑 인디케이터가 여기 속하는 이유**: 멈춘 점 세 개는 "AI가 응답을 멈췄다"로 읽힌다 — 어떤 상태인지 알리는 표시가 아니라 "지금 답을 만들고 있다"는 진행 표시라서, 예외의 근거가 스피너·스켈레톤보다 오히려 세게 적용된다.
- 상태 전달만 한다: 스텝 전환, 팝오버 열림, 게이지 변화. 장식적 등장 연출은 금지.

## 6. Do's and Don'ts

### Do:
- **Do** 색을 쓰고 싶으면 그것이 강조 지점(`primary`/`ring`)인지, 사용자 콘텐츠인지, 위험 액션인지 먼저 확인한다. 셋 다 아니면 무채색이다.
- **Do** 새 표면을 §2의 명도 사다리 위에 올린다(다크 0.160/0.210/0.260/0.300). 사다리에 없는 중간값을 발명하지 않는다.
- **Do** 깊이를 그림자가 아니라 명도로 만든다. 카드가 떠 보여야 하면 `bg-card`를 쓰지 `shadow-md`를 쓰지 않는다.
- **Do** 다크에서 채움 위 텍스트를 뒤집는다 — `primary`와 `destructive` 모두 밝은 채움 + 어두운 텍스트다. 이 쌍을 깨지 말 것.
- **Do** 애니메이션에 `motion-safe:`를 붙인다 — 예외는 §5 Motion에만 적는다.
- **Do** 모든 인터랙티브 엘리먼트에 `focus-visible` 링(`ring-3 ring-ring/50`)을 유지한다(전연령/접근성 정책).
- **Do** 본문에 `text-sm`(1rem)을 쓴다. 이것이 기본값이다.

### Don't:
- **Don't** 다크에서 순백(`oklch(1)`, `text-white`, `#fff`)을 쓰지 않는다. 천장은 `foreground`(0.930)다.
- **Don't** 자극적이거나 성인 지향적인 비주얼 톤을 쓰지 않는다(전연령 정책) — 원색 대비, 네온, 선정적 이미지 트리트먼트.
- **Don't** `primary`를 배경 전체 채우기나 텍스트 그라디언트로 쓰지 않는다. `primary`는 "지금 누를 수 있는 것"과 "지금 내가 한 말"(사용자 말풍선)에만 쓴다.
- **Don't** 솔리드 레드 버튼/배지를 만들지 않는다. destructive는 항상 `/10` 틴트다.
- **Don't** 카드·버튼·인풋에 정지 상태 그림자를 붙이지 않는다.
- **Don't** Toast/Alert에 색상 사이드 보더를 쓰지 않는다. 상태는 아이콘 색과 텍스트로만 구분한다.
- **Don't** 서로 다른 서체 패밀리를 섞지 않는다 — Pretendard 굵기 변화로만 위계를 만든다.
- **Don't** clamp()나 vw 유동 타이포를 쓰지 않는다. 모든 크기는 고정 rem이고 천장은 `text-2xl`이다.
- **Don't** 하단 탭바·전역 사이드 레일·푸터를 추가하지 않는다. 크롬은 `h-14` 헤더 하나다. `<main>` 내부에서 콘텐츠를 여러 열로 나누는 것은 대상이 아니다(판별 기준 §5 Navigation). 이 Don't는 `apps/web` 규칙이다 — `apps/admin`은 예외(§5 Navigation).
- **Don't** 라이트 테마에서 `accent`(0.930) 표면 위에 `muted-foreground`로 본문을 올리지 않는다 — 4.30:1로 AA 미달이다.
- **Don't** `space-y-*`나 `divide-*`를 쓰지 않는다. 간격은 `flex flex-col gap-*`으로만 만든다.
