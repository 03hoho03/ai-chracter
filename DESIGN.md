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
    padding: "16px"
---

# Design System: 또나

## 1. Overview

**Creative North Star: "불 꺼진 방의 유일한 빛(The Only Light in the Room)"**

늦은 밤, 불을 끄고 침대에 누워 혼자 캐릭터와 대화하는 장면. 이 한 장면이 이 시스템의 모든 결정을 강제한다. 방의 조명은 꺼져 있고 **화면이 그 방의 유일한 광원이다**. 사용자의 눈은 이미 어둠에 적응해 있고, 손은 하나뿐이며, 급할 것이 없고, 옆에는 아무도 없다. 그래서 이 인터페이스는 인쇄된 종이가 아니라 **빛을 내뿜는 물건**으로 설계된다 — 밝기는 스타일이 아니라 예산이고, 모든 밝은 표면은 그 예산을 쓴다.

여기서 다크는 선호가 아니라 **기본 조건**이다(`apps/web`는 저장값이 없으면 다크로 부팅한다). 배경이 순수 검정(oklch 0)이 아닌 near-black(0.160)인 것도, 본문이 순백(oklch 1)이 아닌 소프트 화이트(0.930)인 것도 취향이 아니다 — 순수 검정 위의 밝은 텍스트는 OLED에서 번지고 레이어 위계를 쌓을 여지를 남기지 않으며, 어두운 방에서의 순백은 그냥 눈부심이다. 라이트 팔레트는 다크의 열등한 형제가 아니라 **다른 장면**을 위한 것이다: 낮의 사용자, 그리고 항상 라이트로 고정된 관리자 앱(`apps/admin`).

몰입은 시끄러움이 아니라 고요함에서 나온다. 표면(배경·카드·보더 사다리)이 끝까지 무채색인 이유가 이것이다 — 색을 가질 수 있는 것은 사용자가 만든 썸네일, 지금 누를 수 있는 한 곳(`primary`), 채팅에서 "내가 한 말"을 표시하는 1px 선(같은 `primary`, 채움 아님 — Chat Notation 절), 그리고 위험(`destructive`)뿐이다. 그래서 그 한 장과 그 한 버튼이 유일하게 빛난다(제 모양과 색으로 알아봐야 하는 고정 그림 둘 — 재화 클로버 아이콘과 카카오 로그인 버튼 — 은 범위를 좁힌 예외이고, Colors 절의 One-Accent 규칙에 있다). 명시적으로 지양하는 것: 자극적이거나 성인 지향적인 비주얼 톤(전연령 정책), 그리고 어두운 방에서 사용자를 놀라게 하는 모든 것 — 갑작스러운 움직임, 큰 밝은 면적, 예고 없는 대비 점프.

**Key Characteristics:**
- 다크가 기본값(web), 라이트는 낮·admin용 대등한 대안 — 두 팔레트 모두 **표면은 chroma 0**이다
- 다크에서 가장 밝은 값은 `foreground`(0.930)이며 그보다 밝은 것은 존재하지 않는다
- `primary`는 **핑크-레드 강조**이자 이 시스템 자신의 유일한 유채색 솔리드 채움이다(라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`, `ring`도 같은 값). 제3자 로그인 버튼(카카오)의 노랑은 이 시스템의 색이 아니라 그 회사 브랜드 고정색이다(One-Accent 규칙의 예외)
- 그 밖의 유채색은 위험 액션(`destructive`, 언제나 틴트)과 사용자가 고른 스탯 스와치뿐 — 배경·카드·보더 사다리는 무채색을 유지한다. 예외는 재화 클로버 아이콘의 초록과 카카오 로그인 버튼의 노랑 둘이고, 둘 다 그 그림·버튼에만 걸린다(One-Accent 규칙)
- 정지 상태는 평평하다 — 그림자는 앱 전체에 8개뿐이고 전부 다른 것 위로 떠 있는 표면이다
- 상시 크롬은 위쪽 sticky 헤더 한 줄(`h-14`)과, `lg`(1024px) 이상에서 그 왼쪽의 접을 수 있는 좌측 패널 한 열뿐이다 — 하단 탭바도, 두 번째 가로 줄도, 오른쪽 레일도, 고정(sticky/fixed) 푸터도 없다(web 규칙 — admin은 좌측 사이드바를 쓴다, Navigation 절). 패널은 펼침 240px와 아이콘 레일 64px를 오가고, 채팅·이미지 스튜디오에는 접힌 채로 들어오며, 빌더·소설 편집 보드·소설 화 읽기 화면에는 그리지 않는다. 문서 스크롤 화면의 문서 끝에 놓이는 정보 푸터 하나는 크롬이 아니다 — 고정되지 않아 정지 상태에 크롬 줄을 더하지 않고, 채팅·빌더·이미지 스튜디오·소설 화 읽기·소설 편집 보드 화면에는 렌더하지 않는다(Navigation 절). **이 금지의 대상은 전역 크롬이다 — `<main>` 안에서 한 라우트의 콘텐츠를 여러 열로 나누는 것은 대상이 아니다**(판별 기준 Navigation 절). 빌더 라우트(`/builder/*`)와 소설 편집 보드(`/novels/$novelId/board`)는 전역 헤더 대신 같은 56px 자리를 쓰는 전용 상단바(`BuilderTopBar`, 보드는 `NovelBoardTopBar`)로 바뀌고 좌측 패널도 그리지 않는다 — 크롬은 여전히 위쪽 한 줄이다. **또 하나의 예외는 상세화면의 하단 고정 액션 바다** — `lg` 미만에서 주 CTA(플레이) 하나를 화면 하단에 고정한다. 이것은 탭바·좌측 패널 같은 **상시 내비게이션**이 아니다: 화면 전환에 쓰이는 것이 아니라 그 화면의 **단일 전환 액션 하나만** 담는 바다. 이 예외는 상세화면 한 곳에 한정되며 **다른 화면으로 번지지 않는다** — 목록·채팅·빌더에 새 하단 바를 추가할 근거로 쓰지 말 것(admin 상세의 조치 바는 이와 별개의 admin 예외다 — Navigation 절). **소설 화 읽기 화면(`/novels/$novelId/episodes/$chapterId`)은 크롬이 없는 쪽의 예외다** — 전역 헤더도 좌측 패널도 사이트 푸터도 그리지 않는다. 넘김 방식이 둘이다: 기본인 페이지 모드는 본문을 고정 판형(논리 360×540px)의 쪽으로 나눠 화면에 맞춰 키우고 줄이며 좌우로 넘기고(펼쳐도 글자가 작아지지 않는 넓은 화면에서는 두 쪽을 펼친다), 스크롤 모드는 본문을 세로로 이어 읽는다. 정지 상태에는 본문만 있다 — 하나뿐인 예외는 페이지 모드에서 마우스·트랙패드 기기에만 보이는 좌우 넘김 버튼 둘이고, 판형 밖 여백에 본문보다 어둡게 놓여 본문을 가리지 않는다(Navigation 절). 화를 열면(다른 화로 옮긴 뒤에도) 바는 숨은 채로 시작하고, 본문을 탭하거나(페이지 모드는 가운데 영역) "메뉴 열기" 버튼을 누를 때만 위 바(뒤로·화 제목과 화 안 위치·목차·보기 설정)와 아래 바(페이지 모드는 이전 화·쪽 이동 슬라이더·다음 화, 스크롤 모드는 진행 막대와 이전·다음 화)가 나타나며 — 페이지 모드에서는 두 바 자리가 늘 비어 있어 글을 가리지 않고, 스크롤 모드에서는 본문 위에 겹친다 — 다시 탭하면 숨는다. 상시 내비게이션이 아니라 부를 때만 오는 일시적 표면이라 정지 상태의 크롬을 늘리지 않는다. 이 예외는 그 라우트에만 걸리며, 다른 화면에 하단 바·숨는 헤더·상시 넘김 버튼을 둘 근거가 되지 않는다(Navigation 절).

## 2. Colors

**표면은 명도 하나로만 위계를 만들고(무채색 사다리), 색은 강조 지점에만 얹는다.** 레이어 구분은 여전히 색상(hue)이 아니라 밝기 차이로만 하고, 유채색은 `primary`/`ring`·`destructive`·사용자 콘텐츠 셋에만 남긴다(예외 둘 — 클로버 아이콘과 카카오 로그인 버튼 — 은 아래 One-Accent 규칙). 프론트매터는 **기본 테마인 다크**를 담는다. 두 팔레트 모두 `packages/ui/src/styles/globals.css` 한 곳에서만 정의된다.

아래 본문의 oklch 값은 `globals.css`와 **문자열까지 같게** 적는다(프론트매터 블록만 도구 규약상 3자리 정규화 표기 — 같은 값이다). 문서와 코드가 어긋났는지는 grep 한 번으로 확인할 수 있어야 한다.

### Primary
- **Pink-Red Accent (핑크-레드 강조)** — `primary`(= `ring`, 라이트 `oklch(0.5 0.19 0)` / 다크 `oklch(0.72 0.18 0)`): 주요 CTA(플레이, 발행/제출), 사용자 메시지의 1px 좌측선(채움 아님, Chat Notation 절), 포커스 링·보더, 활성 토글, 체크박스·스위치의 on 상태. **이 시스템이 정의한 유일한 유채색 솔리드 채움이다** — `destructive`가 언제나 틴트인 것과 형태로 갈린다. 카카오 로그인 버튼의 노랑 채움은 이 시스템의 색이 아니라 제3자 브랜드 고정색이라 이 문장의 예외다(One-Accent 규칙).
- **채움 위 텍스트는 항상 `primary-foreground`로 뒤집는다**(라이트 `oklch(1 0 0)` / 다크 `oklch(0.16 0 0)`): 라이트 **6.70:1** / 다크 **7.18:1**. 라이트 채움이 더 어두운 것은 그 위에 흰 텍스트를 얹기 때문이다.
- **브랜드 색을 라이트·다크 단일값으로 합치지 않는다 — 검토 후 기각했다**(2026-09-11). 네 조건(양 테마의 채움 위 텍스트 ≥4.5:1, 채움 대 배경 ≥3:1)을 전부 만족하는 단일값 대역 `oklch(L 0.52~0.54)`은 **존재한다** — 그러니 이건 접근성 때문에 못 하는 게 아니다. 기각한 이유는 **다크에서 채움이 배경에서 떨어져 나오는 정도가 7.18:1 → 3.44:1**(카드 위에 앉는 플레이 CTA는 **3.14:1**)로 반토막 나고, 활성 칩의 상대 휘도가 **0.327 → 0.130**으로 떨어지기 때문이다(A/B 렌더 + canvas 실측). "불 꺼진 방의 유일한 빛"에서 유일한 유채색 솔리드 채움이 빛의 60%를 잃는 거래다. **레퍼런스 둘 다 이 문제를 풀지 않았다** — 크랙은 단일값을 쓰되 양쪽 모드 3.43:1로 AA를 포기했고, 케이브덕은 다크 전용이라 라이트 제약을 진 적이 없다(그 자신도 채움 대 배경은 2.83:1이다). **이 결정은 "분홍 채움 위 흰 글자"와 같은 하나의 결정이다** — 흰 글자를 얻으려면 다크 `primary`의 L을 0.54 이하로 내려야 하고 그게 곧 단일값 대역이다.
- **명도는 hover까지 보고 고른 값이다** — `bg-primary/80`(hover)에서도 `background` 위 라이트 **4.77:1** / 다크 **4.90:1**로 AA를 유지한다. 정지 대비만 재고 토큰을 바꾸면 hover에서 깨진다.
- **`text-primary`의 대비 대역은 5.47~7.18:1**이다(background / card / popover / secondary·accent 전부 AA 이상, 최저는 라이트에서 불투명 `secondary`·`accent` 위 5.47 — 다크는 같은 면 위 5.73). `primary`가 `foreground`와 같은 값이던 시절의 15.8:1이 아니므로, 새 표면 위에 `text-primary`를 얹을 땐 이 대역을 하한으로 본다.
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
| `input` | oklch(0.520) | oklch(0.620) | **컨트롤 식별 보더** — 인풋·텍스트에어리어·셀렉트·체크박스·outline 버튼·선택 안 된 토글, 그리고 스위치의 off 트랙(`bg-input`). 보더가 아닌 쓰임은 하나 — 소설 화 읽기 화면 페이지 모드의 넘김 버튼 아이콘 정지 색(`text-input`, 같은 3:1 하한으로 컨트롤임을 알리되 본문보다 어둡게. Navigation 절) |
| `muted-foreground` | oklch(0.680) | oklch(0.530) | 보조 텍스트 — 캡션, 타임스탬프, 조회수, 채팅 지문(Chat Notation 절) |
| `foreground` | oklch(0.930) | oklch(0.220) | 본문 텍스트 |

측정된 대비(WCAG 2.x, sRGB 변환 기준):
- 다크 `foreground` on `background`: **15.79:1** / 라이트 `foreground` on `background`: **17.31:1**
- 다크 `muted-foreground` on `background`: **6.74:1**, on `secondary`: **5.39:1** — 두 레이어 모두 AA 통과
- 라이트 `muted-foreground` on `background`: **5.28:1**, on `card`: **4.84:1** — 통과. 단 **on `accent`(0.930)에서는 4.30:1로 AA 미달**이므로, 라이트에서 `accent` 표면 위에 `muted-foreground`로 본문을 올리지 않는다(배지처럼 큰 텍스트가 아닌 이상).

**표면 위 채움 규칙 — `card`/`popover` 위의 채움·hover·선택 배경은 `secondary`다. `muted`는 `background` 위 첫 레이어(스켈레톤·웰) 전용이다**. 표의 둘째 줄처럼 셋이 **같은 값**이라, 모달(`DialogContent`·`AlertDialogContent`·`SheetContent`)이나 `bg-card` 섹션 안에 깐 `bg-muted` 스켈레톤·웰·hover·선택은 표면 대비 **1.0000:1로 사라진다** — 라이트만의 문제가 아니라 두 테마 모두다. `secondary`로 올리면 대 `card`/`popover` **1.1239 라이트 / 1.1439 다크**(`background` 위 `muted`의 1.0902 / 1.0946과 같은 급)로 보이게 된다.
- **그 채움 위 글자는 `muted-foreground`가 아니라 `foreground`다** — 위 목록대로 라이트 `muted-foreground` on `secondary`는 4.30:1로 AA 미달이다. hover에만 채움이 생기는 행이면 `group` + `group-hover:text-foreground`로 채움과 함께 올린다.
- **안에 outline 컨트롤이 있는 박스는 채움 대신 윤곽(`border border-border`)으로 만든다** — `secondary` 위 `border-input`은 아래 문단대로 3:1 미달이다(2.9714 / 2.8276).
- **`DialogFooter`/`AlertDialogFooter`의 띠만 `secondary/50`이다** — 불투명 `secondary`면 그 위 outline 버튼 보더와 `muted-foreground` 문장이 위 두 줄에 걸린다. `/50`은 띠 1.0642 / 1.0651, 보더 3.1380 / 3.0367, 글자 라이트 4.5259로 셋 다 지킨다.
- **정보를 싣는 선택 상태**(어느 행을 골랐는가)는 채움(card 위 1.12~1.14, background 위 1.23)만으로 WCAG 1.4.11(3:1)에 못 닿으므로 3:1 이상의 단서를 하나 더 둔다(예: admin 프롬프트 버전 이력 표(`VersionHistorySection`)와 공용 `DataList`의 고르는 목록(이의제기)에서 고른 행의 대상 버튼(`aria-current`) 안 글자 앞 체크 글리프, `foreground` on `secondary` 14.06:1). 스켈레톤·웰·hover처럼 정보를 싣지 않는 채움은 위 수치로 충분하다.
- **강제**: `apps/web/src/shared/lib/surface-contract/mutedOnSurfaceContract.test.ts`가 web + `packages/ui` 소스를 스캔한다(주석 제거 후, 표면 표식이 있는 파일의 `bg-muted` 토큰을 실패로 본다). **파일 단위라 표식과 채움이 다른 파일에 있으면 못 잡고**(예: `SheetContent` 안에 렌더되는 `GeneratedImageLibraryPanel`), **admin은 스캔하지 않는다**(형제 앱, vitest 없음) — 둘 다 손으로 조상을 확인한다.
- ⚠️ **공용 프리미티브의 기본값은 아직 이 규칙 밖이다**: `button.tsx` outline·ghost의 `hover:bg-muted`(아래 Buttons 절과 프론트매터 `button-ghost-hover`가 그 값을 적는다), `toggle.tsx`의 `hover:bg-muted`, `tabs.tsx` default 리스트, `avatar.tsx` 폴백, `markdown.tsx` 인라인 코드, `table.tsx`의 hover·선택·footer. 이들이 card/popover 위에 오면 같은 이유로 사라진다 — 기본값을 바꿀 때까지는 **card/popover 위 호출부에서 덮는다**(예: admin `DenseTable`이 `surface="card"`일 때 행 hover를 `secondary/50`, 고른 행을 `secondary`로 덮는다. 호출부가 닿지 않는 `Dialog`·`Sheet` 닫기 X만 프리미티브 안에서 `secondary`로 덮었다). Components 절의 해당 문장은 "`background` 위에서"로 읽는다.

**`border`와 `input`은 값이 다르다 — 사다리에서 갈라져 나온 유일한 무채색 토큰이다.** 둘은 규범이 다르다: `border`가 그리는 구분선·카드 테두리는 장식이라 WCAG 대비 요건이 없지만, `input`이 그리는 컨트롤 테두리는 **비텍스트 대비 1.4.11(3:1)**을 진다 — 인풋·outline 버튼·선택 안 된 토글은 내부 채움이 페이지 배경과 `1.0000`이라 그 한 줄이 "여기 컨트롤이 있다"는 **유일한 신호**이기 때문이다. 사다리 값(0.300/0.890)으로는 **1.4312 다크 / 1.3845 라이트**로 절반도 안 됐다. 채팅의 인용(장면 헤더) 선과 `hr`도 `border`다 — 인용임을 알리는 신호는 작고 흐린 글자와 들여쓰기가 지고 선은 장식이라 이 대비로 충분하다(Chat Notation 절의 인용).
- 고친 값의 실측(스크린샷 픽셀 디코드): 인풋 보더 대 `background` **3.5403 다크 / 3.6408 라이트**, 대 `card`(=`popover`·`muted`) **3.2344 / 3.3395**. 스위치 off 트랙(`bg-input`)과 그 위 흰 썸(`bg-background`)도 같은 값을 얻는다(전 1.4312 → 후 3.5403).
- **`secondary`·`accent`(다크 0.260 / 라이트 0.930) 표면 위에서는 2.8276 / 2.9714로 여전히 미달이다.** 그 두 표면 위에는 보더로만 식별되는 컨트롤을 올리지 않는다 — 올려야 한다면 채움이나 링을 함께 준다.
- **컨트롤 테두리에 `border-border`를 쓰지 말 것.** 손으로 복사한 셸(파일 업로드 라벨, 아이콘·컬러 피커 트리거, 목록형 선택 행)이 이 규칙을 조용히 새게 만든다 — 인터랙티브하면 `border-input`, 구조면 `border-border`다. 예외는 **클릭 카드**(`ContentCard`, `BuilderTypeSelectPage`)로, 거기서는 썸네일·제목·hover·포커스 링이 함께 식별을 지므로 `border-border`를 유지한다(Cards / Containers 절).

### Semantic
- **Destructive (경고 레드)** — 다크 oklch(0.640 0.190 25) / 라이트 oklch(0.550 0.190 25): 삭제/탈퇴/거부/이용제한. `primary`와 함께 시스템 유채색 둘 중 하나이며, 둘은 hue(25 대 0)와 **형태**로 갈린다 — destructive는 언제나 틴트, primary는 솔리드 채움이다. 다크에서 빨강을 밝힌 것은 텍스트 대비를 위해서이며(on `background` **5.27:1**), 그 대가로 **밝힌 빨강 위 흰 텍스트는 3.68:1로 AA에 미달한다** — 그래서 `destructive-foreground`도 함께 어둡게 뒤집는다(0.160, 대비 5.27:1). 토큰을 조정할 때 이 쌍을 반드시 함께 유지할 것.
- **실제 구현에서 destructive는 채움이 아니라 틴트다**: 버튼도 배지도 `bg-destructive/10 text-destructive-text`를 쓴다. 어두운 방에서 솔리드 레드 블록은 그 자체로 놀람이다.
- **Destructive text (경고 레드 · 텍스트 전용)** — 다크 oklch(0.690 0.190 25) / 라이트 oklch(0.490 0.190 25): **틴트 위에 얹는 글자와 글리프는 `--destructive`가 아니라 이 토큰을 쓴다.** 채움 쪽(`bg-destructive/5`·`/10`·`/20`, `border-destructive/30`, `ring-destructive/20`)과 **솔리드 채움 위의 `destructive-foreground` 반전 쌍**은 `--destructive` 그대로다 — 둘을 갈라 둔 이유가 그것이다.
  - 왜 갈랐나: 한 토큰이 글자와 틴트를 겸하면 대비를 올리는 순간 틴트 색까지 함께 움직인다. `--destructive`(라이트 0.55 / 다크 0.64)는 평평한 `background` 위에서만 AA를 아슬아슬하게 넘겼고(라이트 **4.5672** / 다크 4.8402 — 앞은 이번 런에서 재현한 실측, 뒤는 저장소 공표값), `bg-popover`처럼 **사다리 한 칸 안쪽 표면**에 얹히면 rest 4.2059 / 4.3824, hover(`/20`)에서 **3.6035 / 3.8252**까지 떨어졌다.
  - 갈라 낸 뒤 실측(canvas `getImageData`, 전이 정착 후): 최악 조합인 **hover `/20` over `popover`가 라이트 4.6907 / 다크 4.6346**, `/10` over `popover`가 5.4748 / 5.3097, 평평한 `background` 위가 5.9451 / 5.9024다. 틴트 픽셀은 전후 동일하다(A/B로 확인 — `/5` `/10` `/20` 합성 결과가 라이트·다크 모두 바이트까지 같다).
  - 명도는 이 이상 못 민다: 라이트 0.49에서 hue 25의 sRGB 게멋 상한 chroma가 0.1986, 다크 0.69에서 0.1995라 현재 값 0.19가 이미 상한 바로 아래다.

### Tertiary
- **스탯 스와치(User-chosen swatches)** — `packages/ui/src/lib/color-palette.ts`의 10색 고정 팔레트(rose/orange/amber/lime/emerald/teal/sky/indigo/violet/fuchsia, 예: oklch(0.62 0.19 350)). **UI 팔레트가 아니라 사용자 데이터다** — 채팅방 스탯 게이지와 컬러 피커에서 사용자가 직접 고른 값이며, 테마에 따라 변하지 않는다. 시스템 토큰으로 승격하지 말 것.
- **스크림(Scrim) — `--scrim` oklch(0 0 0) / `--scrim-foreground` oklch(0.930 0 0)**: 아트워크 위에 캡션을 얹는 자리 전용이고, **이 쌍만 `.dark`에서 덮이지 않는다**(globals.css `:root`에만 있다). 아래 깔린 것이 팔레트가 아니라 임의의 이미지라, 테마를 따라 뒤집으면 반드시 한쪽이 깨진다 — 스크림은 테마와 무관하게 어두운데 그 위 글씨만 라이트에서 어두워지기 때문이다. `--scrim-foreground`의 0.930은 밝기 예산 규칙의 천장과 같은 값이라 순백 금지를 지킨다. **쓸 때는 `bg-scrim/70` 불투명 밴드다** — 그래야 아트워크가 무엇이든 최악(순백 픽셀)에서 6.93:1이 보장된다. 옅은 그라데이션(`bg-gradient-to-t from-scrim/60`)으로 깔면 글자 윗단에서 알파가 0.28까지 떨어져 그 보장이 사라진다(실측: 다크 1.65:1 · 라이트 1.67:1로 양쪽 다 미달이었다). 지금 쓰는 곳은 `GenerateImagesStyleGrid`의 스타일 타일 이름표, 빌더 미디어 북 배치표 칸 위의 두 표식(대화 제외 표식·상황 설명 없음 표식, Components 절의 Media images), 생성 이미지 고르기 모달에서 미디어 북 칸을 채울 때 그림 위에 얹는 `지금 이미지`·`사용 중` 표식, 배치표의 채운 칸에 바꿀 그림을 올리는 동안 가운데 서는 스피너 자리, 그리고 이미지 스튜디오 결과 타일에서 상세를 열려고 목록을 기다리는 동안 가운데 서는 스피너 자리다.
- **테마 쌍 면 — 이미지 위 글자의 두 번째 방식(보관함 잠긴 칸)**: `bg-background/75` 면 위에 `text-foreground` 글자다. 스크림 규칙이 막는 실패는 "면은 테마와 무관하게 어두운데 글자만 라이트에서 어두워지는 것"인데, 이 면은 글자와 **함께** 뒤집혀 그 실패가 생기지 않는다 — 그래서 스크림 규칙의 위반이 아니다. 면 알파 0.75에서 밑 픽셀이 최악일 때 다크 **7.25:1**(순백 픽셀) · 라이트 **9.44:1**(순흑 픽셀)이다(sRGB 알파 합성 계산, 실측 아님). 0.6으로 낮추면 다크가 **4.15:1**로 AA에 못 미친다. 스크림과 실제로 달라지는 것은 라이트뿐이다 — 스크림이면 흰 다이얼로그 안에 검은 면이 서고, 테마 쌍이면 면이 다이얼로그와 같은 쪽으로 뒤집힌다.

### Named Rules
**The Brightness Budget Rule (밝기 예산 규칙).** 화면은 방의 유일한 광원이다. 다크 테마에서 `foreground`(0.930)보다 밝은 값은 **존재하지 않는다** — 순백(oklch 1.000)은 다크에서 금지다. 밝은 표면은 예산이고, 단위는 **면적**이다. 하지만 실제로 지켜지는 제약은 치수 상한이 아니다 — `CharacterPlayBar.tsx`·`StoryPlayBar.tsx`의 플레이 버튼은 `primary` 솔리드 채움에 `h-12 w-full`이라 데스크톱 472×48 ≈ 22,700px²로 `h-8` 버튼의 약 15배지만 예산을 어기지 않는다, 그 화면의 유일한 전환 지점이기 때문이다. 지켜지는 규칙은 **"밝은 면적은 예산이고, 한 화면에서 지금 눌러야 할 단 하나에만 쓴다"**이다: 무채색 variant(`outline`·`ghost`·`secondary`)의 확대는 이 예산을 전혀 쓰지 않고, `primary` 솔리드 확대는 **화면당 하나**라는 제약으로 관리한다 — 치수 상한이 아니다. `destructive`는 언제나 틴트라 애초에 이 예산 밖이다. **두 가지 오독을 차단한다**: ① "단위가 높이니 패딩은 공짜다"가 아니다 — 원문 단위는 면적이라 가로로 넓혀도 그만큼 예산을 쓴다. ② "규칙이 거짓이니 밝기는 신경 안 써도 된다"가 아니다 — 거짓이었던 건 `h-8`이라는 **수치 상한 주장**이지 예산 개념 자체가 아니다. 핑크-레드로 바뀐 뒤에도 다크 `primary`의 L(0.72)은 이 천장 아래에 있다. 채팅의 사용자 메시지는 한때 `primary` 솔리드 채움 말풍선이라 메시지마다 한 화면에 여러 번 이 예산을 썼다 — 지금은 1px 좌측선이라 면적이 사실상 없다(Chat Notation 절의 레이아웃). **예외 하나 — 로그인·회원가입 화면의 카카오 로그인 버튼**은 카카오 브랜드 가이드의 고정색(`#FEE500`, OKLCH L ≈ 0.914로 `foreground` 천장 아래)을 그대로 써서, 그 화면에서 `primary` 제출 버튼과 함께 두 번째 밝은 면적을 쓴다. 가이드가 색 변경을 금지해 예산에 맞춰 낮출 수 없기 때문이다. 대신 소셜 버튼 묶음 안에서 채움은 카카오 하나뿐이다(구글은 `outline`). 이 예외는 그 버튼에만 걸리고, 다른 화면에 두 번째 솔리드 채움을 둘 근거가 되지 않는다.

**The Inverted Ladder Rule (반전 사다리 규칙).** 다크에서는 위로 뜨는 레이어일수록 밝아진다(0.160 → 0.210 → 0.260 → 0.300). 라이트에서는 정확히 반대다(1.000 → 0.970 → 0.930 → 0.890). 새 레이어를 추가할 때 이 사다리에 없는 중간값을 발명하지 말 것.

**The One-Accent Rule (강조는 하나뿐 규칙).** 색이 존재할 수 있는 곳은 셋뿐이다 — 강조 지점(`primary`/`ring`), 사용자 콘텐츠(썸네일, 스탯 스와치), 위험 액션(`destructive`). 배경·카드·보더 사다리와 그 위의 텍스트·배지·비활성 컨트롤은 끝까지 무채색이다. 새 UI 색(성공 그린, 정보 블루, 브랜드 세컨더리)을 발명하지 말 것 — 상태는 아이콘과 텍스트로 구분한다. 예외는 둘이다. 하나는 재화 클로버의 아이콘이다 — 재화의 얼굴이라 어느 화면에서든 같은 모양·같은 색으로 알아봐야 해서 초록으로 고정된 그림(`entities/clover/ui/CloverIcon.tsx`)으로 둔다. 예외는 그 그림에만 걸린다: 곁의 숫자·문구·버튼·배지는 무채색이고, 초록을 상태색(성공 등)이나 다른 UI로 번지게 하지 않는다. 다른 하나는 제3자 로그인 버튼(카카오)이다 — 그 회사 브랜드 가이드가 컨테이너·심볼·레이블 색을 정하고 변경을 금지하므로, 다크에서도 같은 노랑(`#FEE500`)과 먹색(`#191919`)을 쓴다(`features/login/ui/KakaoLoginButton.tsx`, 값은 그 파일 한 곳에만 있다). 예외는 그 버튼에만 걸린다: 노랑을 토큰이나 `packages/ui` variant로 올리지 않고, 다른 UI로 번지게 하지 않는다. 노랑 위에서는 기본 포커스 레시피가 3:1에 못 미치므로 `primary` 솔리드 채움과 같은 불투명 링을 쓴다. 그리고 강조는 **하나**라는 뜻이기도 하다: 한 화면에서 `primary`로 칠할 것을 고를 때 "지금 누를 수 있는 것"과 "지금 내가 한 말"(채팅 사용자 메시지의 1px 좌측선) 밖으로 번지면, 썸네일 한 장이 유일하게 빛난다는 전제가 무너진다. 두 범주는 나란하다 — 뒤의 것은 누를 수 있는 것이 아니지만 사용자 자신의 흔적이라 강조를 받는다. 다만 채움이 아니라 선이라 밝기 예산을 거의 쓰지 않는다.

## 3. Typography

**Display / Title / Body / Label Font:** Pretendard Variable (with `-apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Malgun Gothic', sans-serif`)

`--font-heading`은 `--font-sans`의 별칭이다(`globals.css`) — 제목용 별도 서체는 존재하지 않으며, `font-heading`은 `apps/` 코드에서는 `ChatMoreSidebar.tsx`·`ChatMemorySidebar.tsx` 두 곳, `packages/ui`에서는 Dialog·Sheet·AlertDialog 제목 3곳에 쓰인다(별칭이라 렌더는 `font-sans`와 같다).

**Mono(예외):** `--font-mono`(`ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace, "Pretendard Variable"`)는 **채팅 코드 블록 한 자리**를 위해 둔 기기 고정폭 스택이다(웹폰트를 받지 않는다, 순서의 이유는 Chat Notation 절의 코드 블록). Tailwind 기본 스택을 덮으므로 `font-mono`를 쓰는 곳은 전부 이 값을 따른다.

**Character:** 한글 가독성이 검증된 단일 휴머니스트 산세리프를 굵기(weight)만 바꿔 전 화면에 쓴다. 실제로 코드에 존재하는 굵기는 셋이다 — medium(500) / semibold(600) / bold(700). 아래 단일 서체 규칙의 예외는 둘이다 — 상속 굵기를 본문 400으로 되돌리는 리셋용 `font-normal` 14곳(web 12·admin 2, 주석 제외), 그리고 채팅 코드 블록의 고정폭(`font-mono`). 크기 스케일도 `text-2xl`(1.5rem)에서 멈춘다: 이 제품에는 히어로가 없고, 가장 큰 글자도 페이지 제목이다. 예외는 둘이다 — `/about`(서비스 소개)의 태그라인 한 줄, 그리고 소설 화 읽기 화면 페이지 모드의 판형 배율(아래 히어로 없음 규칙).

### Hierarchy
- **Display** (700, 1.5rem/2rem, -0.025em): 페이지 제목(h1) 전용. 화면 내 최상위. **h1이 아닌 곳에 쓰지 않는다 — 예외가 0이다**: web의 `text-2xl` 19곳(`ui-demo` 견본·주석 제외) 중 18곳이 h1이고(admin은 전부 h1) 나머지 하나는 아바타 이니셜 글리프다. 소설 작품 정보 화면의 제목과 화 읽기 화면의 화 제목도 이 h1이다(화 읽기 화면의 제목은 읽기 글자 크기 설정과 무관하게 이 크기다). 반대 방향의 예외가 하나 있다 — `/about`의 h1은 Display가 아니라 태그라인 위의 작은 라벨(`text-sm font-semibold text-muted-foreground`)이다. 그 화면의 첫 인상은 h1이 아닌 태그라인(`<p>`, `text-4xl`)이 맡고, h1 문구는 헤더 메뉴·푸터의 링크 이름과 같아야 해서 바꾸지 않았다(히어로 없음 규칙). (이 줄은 한때 "마이페이지 섹션 제목"을 포함했다. 그건 규칙이 아니라 한 파일의 예외였고 — 그 화면의 h1과 h2는 계산된 속성 580개가 **전부 일치**해 헤딩으로 훑으면 넷이 동일하게 읽혔다 — 그 h2 셋을 Title로 내리면서 이 예외는 사라졌다.)
- **Title** (600, 1.25rem/1.75rem, -0.025em): 인증 화면 제목, 카드 제목, **설정 섹션 제목(h2)**. 페이지 제목 아래 한 단계가 필요한 자리는 전부 여기다.
- **18px 소제목** (`text-lg`, 1.125rem/1.75rem, 굵기는 자리에 따라 `font-semibold`(카드·목록·빈 상태 제목) 또는 `font-medium`(Dialog/Sheet/AlertDialog 제목)): Title(20px)보다 한 단계 낮은 강조가 필요한 소제목. **2026-09-11 타이포 사다리 개편 전엔 이 문서에 없던 6번째 크기였다** — 당시 `text-base`(Tailwind 기본값, 16px)로 17곳이 손조립돼 있었는데, 그 개편이 Body(`--text-sm`)를 16px로 올리면서 `text-base`와 값이 같아져 위계가 붕괴할 뻔했다. 같은 개편에서 그 17곳을 `text-lg`(18px)로 옮기며 이 자리를 사다리의 정식 티어로 승격했다.
- **Body** (400, 1rem/1.4286rem): 본문, 대화 메시지, 설명. 앱에서 여전히 가장 많이 쓰이는 크기다(재측정 `text-sm` 약 205회 — `grep -rnE '\btext-sm\b' apps/web/src --include='*.tsx'`, 주석 제외 — Label(`text-xs`) 약 168회를 앞선다)이며 **사실상의 기본값**이다. 산문은 65-75**자**(문자 수 기준 — `ch` 단위가 아니다, 한글은 글리프가 전각이라 두 단위가 갈린다)에서 줄바꿈이 규범이다. 채팅 실측은 1512px에서 61~71자로 이 규범 안에 들고(`max-w-3xl` 캡, 표기 도입 전 캐릭터 산문으로 잰 값 — LLM 출력마다 줄바꿈이 달라 폭이 흔들린다, 유저 메시지도 같은 캡이다), 390px는 폰 폭이 물리적으로 좁아 규범 달성이 아니라 낭비 제거가 목표다. 소설 화 읽기 화면 페이지 모드는 판형 폭(논리 360px, 글 상자 312px)이 줄 길이를 정해 어느 기기에서나 같다 — 실제 화 본문으로 잰 한 줄(공백 포함, 문단 마지막 줄 제외) 중앙값이 글자 보통 24자·크게 21자·더 크게 19자다. 이 규범보다 짧은 것은 폰이 주 사용처인 화면에서 폰 배율을 약 1.0 으로 두려고 고른 값이라서다(폭을 넓히면 같은 폰에서 글자가 작아진다). 넓은 화면은 판형을 펼쳐 두 쪽을 나란히 놓을 뿐 줄을 늘리지 않는다. 스크롤 모드는 본문 상자(좌우 여백 포함)의 폭 상한이 `max-w-prose`(65`ch`)라 넓은 화면에서 한 줄 약 50자다(목업 값 — 실제 화 본문으로 다시 잰다). 그래서 넓은 화면에서는 두 모드의 줄 길이가 다르다. **채팅 본문의 줄높이는 이 토큰(1.4286rem)이 아니라 `leading-relaxed`(1.625, 16px에서 26px)다** — 표기 도입 전의 말풍선·산문도 같은 값이었고, 렌더러가 그 값을 이어받았다(Chat Notation 절의 렌더).
- **Label** (500, 0.875rem/1.1667rem): 폼 라벨, 캡션, 메타(조회수·타임스탬프), 에러 텍스트.
- **Badge** (500, 0.75rem = 12px): 상태 배지 전용. `text-xs`(현재 Label, 14px)는 배지 안에서 너무 크다. **Tailwind 숫자 사다리(xs/sm/base…) 밖의 값이지만 임의값이 아니라 토큰이다** — `globals.css`의 `--text-badge`로 두고 호출부는 `text-badge`를 쓴다. (한때 호출부 6곳이 `text-[11px]`를 손으로 적었고 이 줄은 "이 한 티어를 위해 스케일을 늘리지 않았다"로 그걸 정당화했다. 같은 임의값이 6번 반복되면 승격이 규칙이고, 사다리에 칸을 끼우는 것과 **이미 이름 붙은 티어를 시맨틱 토큰으로 실체화하는 것**은 다르다 — `text-2xs`가 아니라 `text-badge`인 이유다. 줄높이는 짝으로 두지 않았다: 이전 `text-[11px]`도 font-size만 설정했으므로 여기서 정하면 6곳의 렌더가 바뀐다. 값은 2026-09-11 타이포 사다리 개편에서 11px→12px가 됐다.)

### Named Rules
**The Single Family Rule (단일 서체 규칙).** 새 화면에 다른 서체 패밀리를 추가하지 않는다. 위계는 굵기·크기·자간으로만 만든다. `font-medium` / `font-semibold` / `font-bold` 셋 밖의 굵기를 도입하지 말 것. 단 `font-normal`은 상속된 굵기를 본문 400으로 되돌리는 리셋에만 허용한다. **고정폭은 예외다 — 범위는 채팅 코드 블록(칸을 맞춘 글)뿐이다.** 새 패밀리를 싣는 것이 아니라 기기의 고정폭 서체를 `--font-mono` 한 토큰으로 부르고, 한글은 그 스택 끝의 Pretendard가 그대로 잡는다. 인라인 코드는 채팅에서도 공용 `markdown.tsx`에서도 고정폭을 쓰지 않는다. 이 규칙 전부터 `font-mono`를 쓰던 두 곳 — `packages/ui` `chart.tsx`의 툴팁 수치, admin `SectionRow.tsx`의 프롬프트 슬롯 이름 — 도 같은 토큰을 따르게 됐다(Tailwind 기본 스택을 덮었으므로). 새 자리에 고정폭을 더하려면 이 범위부터 고친다.

**The No-Hero Rule (히어로 없음 규칙).** `text-2xl`(1.5rem)이 천장이다. 이 제품은 랜딩 페이지가 아니라 사용자가 이미 들어와 있는 도구다 — 큰 글자로 설득할 대상이 없다. clamp()나 vw 기반 유동 타이포는 쓰지 않는다(모든 크기는 고정 rem). **예외는 `/about`(서비스 소개) 하나다** — 이 화면만은 아직 들어오지 않은 사람에게 서비스를 설명하는 자리라, h1 바로 아래 태그라인 **한 줄**(`<p>`, 헤딩 아님)에 `text-4xl`(2.25rem, Tailwind 기본 고정 rem)을 쓴다. 범위는 그 한 줄뿐이다: 같은 화면의 h2·본문은 평소 사다리(Title·Body)를 따르고, clamp()·vw는 여기서도 쓰지 않는다. **이 예외는 다른 화면으로 번지지 않는다** — 홈·상세·공지처럼 소개 성격이 있어 보이는 화면도 천장은 `text-2xl`이다.

**예외 둘째는 소설 화 읽기 화면 페이지 모드의 판형이다.** 그 화면은 쪽 수를 기기와 무관하게 고정하려고 본문을 논리 360×540px 판형에 조판하고 판형 전체를 화면에 맞춰 키우고 줄인다(Navigation 절). 그래서 판형 안에서만 두 규칙이 풀린다 — ① 크기는 rem 이 아니라 **px 로 고정**한다(rem 이면 브라우저 기본 글자 크기 설정이 쪽 수를 바꾼다), ② 화면에 보이는 크기가 **뷰포트에 따라 연속으로 변한다**(판형 px × 배율). 배율은 0.8~1.2 로 묶는다 — 상한 1.2 는 본문 설정 최대 20px 이 24px(`text-2xl`)에 닿는 값이고, 판형 안 화 제목(24px)만 그 위로 28.8px 까지 간다. 하한 밑이면 그 기기에서는 스크롤 모드(평소 rem 사다리)로 보인다. **판별: 소설 화 읽기 라우트 · 페이지 모드 · 판형 상자 안 — 셋이 모두 참인 글자만 이 예외다.** 같은 화면의 위·아래 바, 보기 설정 패널, 목차 시트, 스크롤 모드 본문은 평소 사다리 그대로이고, clamp()·vw 는 여기서도 쓰지 않는다(크기를 정하는 것은 배율 하나다). 이 예외는 다른 화면으로 번지지 않는다.

## 4. Elevation

**이 시스템은 사실상 그림자가 없다.** 깊이는 그림자가 아니라 Colors 절의 명도 사다리(tonal layering)로 표현한다 — 다크에서 카드가 배경 위에 있다는 것은 그림자가 아니라 `card`(0.210)가 `background`(0.160)보다 밝다는 사실로 전달된다. **예외는 카드 자체가 주 인터랙션인 경우다** — 그때는 hover가 보여야 해서 표면이 `background`로 내려가고 깊이를 `border` 한 줄이 대신한다(Cards / Containers 절). 이것이 "불 꺼진 방"에서 옳은 선택이다: 어두운 방에서 드리운 그림자는 보이지도 않고, 보이게 만들려면 배경을 더 어둡게 깎아야 하는데 그럴 여지가 없다.

앱 전체에 그림자는 **8개뿐이며**, 전부 화면 위로 떠 있는 표면이다 — 손으로 만든 팝오버 4개(단축어 자동완성, 댓글 멘션 자동완성, 컬러 피커, 아이콘 피커)와 web 이 쓰는 `packages/ui` 프리미티브 4개(드롭다운 메뉴, `Select` 목록, `Sheet`, `Tooltip` — 좌측 패널 레일의 이름표). (2026-10-02 `shadow-*` 전수 grep 으로 다시 셌고, 좌측 패널과 함께 `Tooltip`이 더해졌다. web 이 쓰지 않는 프리미티브 변형 — 드롭다운 하위 메뉴, 기본 변형 탭, admin 전용 차트 툴팁 — 은 세지 않는다.) 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다. **미디어 북 배치표의 sticky 장면 이름 열에 걸린 `shadow-[…]` 는 그림자로 세지 않는다** — 번지기 0·퍼짐 0의 `background` 색 오프셋으로 열의 면을 칸 사이 틈까지 넓혀, 가로로 민 칸이 그 틈으로 비치지 않게 하는 채움이다. 셀 배경을 좌우로 넓힌 것과 픽셀이 같아 깊이를 만들지 않는다(셀이 `truncate` 라 의사 요소가 잘리고, 셀 구조를 바꾸지 않고 왼쪽과 오른쪽을 서로 다른 폭으로 넓힐 수단은 흐림 없는 box-shadow 다). `shadow-*` 로 감사할 때 이 한 곳이 걸리는 것은 의도다.

### Shadow Vocabulary
- **Floating panel** (`shadow-md` + `ring-1 ring-foreground/10`): 트리거 위에 떠서 열리는 커스텀 팝오버 전용. `Tooltip`도 상류의 반전 말풍선 대신 이 레시피(`bg-popover`)를 쓴다 — 다크에서 0.930 말풍선이 갑자기 켜지는 것은 예고 없는 대비 점프다. 그림자만으로는 다크에서 경계가 보이지 않으므로 **반드시 `ring`과 함께 쓴다** — 이 조합이 다크에서 실제로 경계를 만드는 것은 ring 쪽이다.
- **Overlay scrim** (`bg-black/10` + `backdrop-blur`): Dialog/Sheet/AlertDialog 배경. **라이트/다크 공통 하드코딩이며 의도된 것이다**(2026-07-17 다크모드 전 화면 시각 검증에서 판정) — 다크에서는 블러가 배경 분리를 담당한다. 시맨틱 토큰으로 바꾸지 말 것.

### Named Rules
**The Flat-at-Rest Rule (정지 시 평평 규칙).** 카드·버튼·인풋은 정지 상태에서 그림자를 갖지 않는다. 그림자는 z축으로 실제로 떠 있는 엘리먼트에만 붙는다. 감사 테스트: 새 컴포넌트에 `shadow-*`를 쓰려 한다면, 그것이 클릭으로 열려서 다른 것 위에 뜨는 물건인지 자문하라. 아니라면 `border`를 쓴다. 소설 편집 보드의 캔버스 라이브러리(`@xyflow/react`)는 동작용 `base.css`만 가져온다 — 기본 테마 `style.css`는 노드 hover·선택과 컨트롤 묶음에 그림자를 걸어 이 규칙과 부딪힌다. 보드 카드의 깊이는 다른 카드처럼 `border` 한 줄이 진다.

**The Ring-Not-Shadow Rule (그림자 대신 링 규칙).** 다크에서 떠 있는 표면의 경계는 그림자가 아니라 `ring-1 ring-foreground/10`이 만든다. 그림자를 더 진하게 키워 경계를 만들려 하지 말 것 — 어두운 배경 위에서는 아무리 키워도 보이지 않는다.

## 5. Components

캐주얼하지 않고 **조용하다**. 컴포넌트는 작고(기본 높이 36px), 라운드는 부드럽지만 장식적이지 않으며, 반응은 즉각적이되 과장이 없다. 밤에 한 손으로 쓰는 물건의 성격이다.

**반경 정책: 같은 높이 티어는 같은 반경을 쓴다** — 32px 티어(`Button`의 `sm`·`icon-sm`, `SelectTrigger sm`)는 `lg`(8px), 24px 티어(`xs`·`icon-xs`)는 `min(md,10px)`(6.4px). 반경 캡이 따로 남아 있으면 같은 32px 안에서 모서리가 갈린다. **`Toggle`은 이 정책의 예외다** — 필터 칩과 액션 버튼을 형태로 가르기 위해 `rounded-full`(pill)을 쓴다. 같은 32px 티어 안에서 `Button`/`SelectTrigger`와 반경이 달라지는 것은 실수가 아니라 "칩과 버튼은 다른 물건"이라는 신호다(아래 §Toggles) — `apps/web/CLAUDE.md`도 `SelectTrigger size="sm"`과 칩이 높이 32px·보더·배경은 같고 **반경만 칩이 pill로 바뀐 뒤 갈린다**고 적는다.

### Buttons
- **Shape:** radius `lg`(8px; `xs`/`icon-xs`만 6.4px, §반경 정책), 기본 높이 `h-9`(36px). 크기 4단계(`xs` 24px / `sm` 32px / `default` 36px / `lg` 40px)와 아이콘 전용 4종. 48px(`h-12`, 플레이 버튼 2곳)은 이 사다리에 없는 호출부 오버라이드 예외다.
- **Primary:** 핑크-레드 `primary` 채움 + `primary-foreground` 텍스트, hover 시 `bg-primary/80`. 다크에서는 밝힌 핑크 + 어두운 텍스트, 라이트에서는 어두운 핑크 + 흰 텍스트 — **규칙은 "채움 위 텍스트를 뒤집는다"로 동일하다**(Colors 절의 Primary).
- **Outline:** `border-input` + `background`, hover 시 `bg-muted`. **보더는 `border`가 아니라 `input`이다** — 채움이 배경과 같아 이 한 줄이 유일한 식별 신호이고 3:1을 진다(Colors 절의 Neutral).
- **Secondary:** `secondary` 채움, hover는 `color-mix(in oklch, var(--secondary), var(--foreground) 5%)` — 사다리를 벗어나지 않도록 토큰에서 파생시킨다.
- **Ghost:** 투명, hover 시 `bg-muted`. **`background` 위 기준이다** — card/popover 위에서는 hover가 사라지므로 호출부에서 `hover:bg-secondary`로 덮는다(`Dialog`·`Sheet` 닫기 X는 프리미티브가 이미 덮었다. Colors 절의 "표면 위 채움 규칙". 할 일: 프리미티브 기본값 자체를 바꾸는 것은 아직 남아 있다).
- **Destructive:** **채움이 아니라 틴트다** — `bg-destructive/10 text-destructive-text`, hover 시 `/20`. 솔리드 레드 버튼은 이 시스템에 존재하지 않는다. **포커스는 하우스 레시피의 hue만 바꾼다** — `focus-visible:border-destructive` + `ring-destructive/50`. 알파를 낮추지 말 것: 보더 40% · 링 20%였을 때 포커스가 **어느 쪽으로도 보이지 않았다**(링 대 배경 1.2371 다크 / 1.3694 라이트, 링 대 자기 채움 1.1312 / 1.1728 — 이 앱에서 포커스가 사실상 안 보이는 유일한 컨트롤이었다). 불투명 보더는 자기 채움 대비 **4.8431 / 4.5795**, 배경 대비 **5.2933 / 5.3328**이다.
- **Link:** `text-primary` + underline-offset-4.
- **Press feedback:** `active:translate-y-px` — 1px 눌림. 이게 이 시스템의 유일한 촉각 신호다(팝오버를 여는 버튼은 제외).
- **Focus:** `focus-visible:ring-3 ring-ring/50` + `border-ring`. 항상 노출한다. **3:1을 지는 건 50% 링이 아니라 불투명 1px 보더다** — 링은 페이지 배경 대비 2.5757 다크 / 2.5511 라이트지만 보더는 자기 채움 대비 **7.1768 / 6.7011**이다(실측). 그래서 이 레시피는 **보더가 살아 있는 한** 성립한다. **채움이 `primary` 솔리드면 무너진다** — 보더가 채움과 같은 색이 되어 사라지므로 링을 불투명으로 올린다(아래 §Toggles). `/10` 틴트 채움(destructive, `toggle` `list`)은 보더가 남으므로 hue만 갈아끼우면 된다. **보더가 없는 컨트롤** 가운데 문장 밖에 홀로 선 텍스트 링크·버튼(콘텐츠 카드·로고·카드 안 작가 버튼·모달 작가 링크·해시태그·푸터 링크)은 불투명 1px 아웃라인이 그 몫을 진다 — `focus-visible:outline-1 focus-visible:outline-ring` + 같은 50% 링. 아웃라인은 보더와 같은 `ring` 색이라 배경 대비 값도 위 보더와 같고, 레이아웃을 먹지 않는다(투명 보더로 대신하면 1px가 자리를 차지해 카드 썸네일이 카드 가장자리와 어긋난다). 반투명 링만 있으면 3:1 미달이다. 이미 아웃라인을 지우는 프리미티브(`outline-none`)는 대상이 아니다 — 그쪽은 보더가 진다. 문장 속 인라인 링크는 여기서 빠진다 — 3px 링이 라인박스를 깨므로 `apps/web/CLAUDE.md` 포커스 절의 규칙대로 `focus-visible:underline`으로 표시한다.

### Toggles (선택 칩 / 목록형 선택지)
단일선택 토글은 `packages/ui/src/components/toggle.tsx`의 `toggleVariants` 하나에서만 정의된다 — 장르 필터, 헤더의 캐릭터/스토리, 테마 선택, 빌더의 시작설정·공개범위가 전부 같은 프리미티브다. 스탯·상황 노트·엔딩 탭 머리의 시작설정 칩은 시작설정이 둘 이상일 때만 그린다 — 하나면 고를 것이 없는데 선택된 칩 하나가 솔리드 채움으로 화면에서 가장 밝은 물체가 되므로, 칩 대신 "‘이름’의 스탯" 문장으로 어느 시작설정의 목록인지만 알린다(`widgets/build-story/ui/StartingSetupPicker.tsx`). 헤더·드로어에서 캐릭터/스토리 옆에 놓이는 "노벨" 링크는 토글이 아니라 `/webnovels`로 가는 내비 링크라 `ToggleGroup` **밖**에 두지만(radio 그룹의 화살표 이동·선택 의미에 섞이지 않게), 시각은 `toggleVariants({ variant })`를 그대로 빌리고 활성 표시는 `data-state="on"`으로 켠다 — 선택 표시를 호출부 클래스로 따로 만들지 않는다(아래 금지 규칙과 같은 이유). 캐릭터/스토리 쪽은 **홈에서만** 선택이 켜진다(값 = 홈 URL의 `?type=`, 없으면 스토리). 홈 밖 화면(노벨 화면 포함)은 어느 유형에도 속하지 않아 토글 값이 비어(`""`) 아무것도 선택되지 않고, 누르면 그 유형의 홈으로 간다.

- **Shape:** 칩은 `sm`(높이 32px), 그 밖은 `default`(36px) — 둘 다 radius `rounded-full`(pill)로 같다. 테두리 `border-input`, 배경 투명. **§반경 정책의 예외다** — 크랙·케이브덕 둘 다 필터 칩(pill/8~16px)과 액션 버튼(4px)을 반경으로 가르는데, 이 프리미티브는 2026-09-11 전까지 `Button`과 같은 `lg`(8px)를 써서 형태로 안 갈렸다. 헤더의 캐릭터/스토리 토글은 **더 이상 pill이 아니다** — 크랙·케이브덕처럼 글자색만으로 활성/비활성을 가르는 텍스트 탭으로 바꾸겠다는 예고가 2026-09-14 실행됐다. 그 토글은 이제 `variant="tab"`을 쓴다(아래). **`variant="list"`는 pill을 안 받고 `lg`(8px)로 남고, `variant="tab"`은 pill도 `lg`도 아닌 `rounded-md`다** — 아래 각각 참조.
- **선택 상태는 `primary` 솔리드 채움 + `primary-foreground` 텍스트**다(Colors 절의 Primary가 "활성 토글"을 primary 용처로 명시). 다크 **7.18:1** / 라이트 **6.70:1**, hover(`bg-primary/80`)에서도 **4.90:1** / **4.77:1**로 AA를 유지한다.
- **예외 — 필터 칩 줄의 기본값 항목은 선택돼도 채우지 않는다.** 아무것도 거르지 않는 항목(홈 장르 줄의 `전체`)이 솔리드로 켜져 있으면, 필터를 하나도 안 건 기본 화면에서 그 칩이 화면에서 가장 밝은 물체가 된다 — 밝기 예산 규칙("화면당 `primary` 솔리드 채움은 하나, 지금 눌러야 할 단 하나에만")을 아무 일도 안 하는 상태에 쓰는 셈이다. 그래서 필터가 실제로 걸렸을 때만(다른 장르를 고르면) 채움이 켜진다. 위 "선택 = 솔리드" 문장과 아래 `list` 항목의 "화면당 솔리드 하나" 문장이 기본 화면에서 부딪히던 자리를 이 예외가 정리한다. 기본값 항목의 선택 표시는 **`border-foreground` + `text-foreground`**다(비선택은 `border-input` + `text-muted-foreground`) — 보더 대 배경 다크 **15.79:1** / 라이트 **17.31:1**, 비선택 보더(`border-input`)는 **3.52:1** / **3.64:1**이라 둘이 갈린다(OKLCH→sRGB 계산값, 픽셀 실측 아님). 구현은 항목에 `data-filter-default` 표식을 달고 `outline` variant가 그 표식에만 규칙을 건다 — 어느 항목이 기본값인지는 variant가 알 수 없어 항목 표식으로 가르고, 규칙이 프리미티브 안에 있어 아래 "호출부에 선택 상태 클래스 금지"를 지킨다. 표식이 없는 칩은 그대로다. **지금 표식을 단 곳은 홈 장르 `전체` 하나뿐이다** — 내 작품 종류·프로필 공개여부·어드민 필터의 `전체`는 아직 솔리드로 켜진다(이 규칙과 다른 칩으로 남아 있다).
- **비활성 글자는 `text-muted-foreground`다**. 이전엔 상속받은 `foreground`(0.930, 다크에서 사실상 밝기 천장)를 그대로 썼는데, 크랙·케이브덕은 비활성 → 활성 방향으로 밝기가 오르는 반대 구조다(크랙 탭 43%→96%, 케이브덕 탭 36%→100%). 비활성이 이미 천장이면 활성에서 올릴 데가 없어 방향이 반대로 읽혔고, 홈 화면에서 선택 안 된 장르 칩 10개가 전부 그 천장을 쓰는 건 Colors 절의 밝기 예산 규칙("밝은 면적은 예산이고 한 화면에서 지금 눌러야 할 단 하나에만 쓴다")과 정면으로 어긋났다. 대비 실측(canvas 변환): 다크 on `background` **6.74:1** / on `card` **6.16:1**, 라이트 on `background` **5.25:1** / on `card` **4.82:1** — 전부 AA(4.5:1)를 넘는다. **보더(`border-input`)는 그대로 둔다** — 이 사다리에서 3:1을 넘는 유일한 무채색 값이라(`border`는 다크 1.43:1 / 라이트 1.38:1로 이미 미달, Colors 절의 Neutral) 더 낮출 자리가 없다.
- **선택 상태를 `bg-muted`로 칠하지 말 것.** 상류 shadcn 기본값이지만 이 시스템에서 그 값은 `background`와 명도가 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160, **1.0946:1**) 선택이 보이지 않고, `hover:bg-muted`와 색이 같아 선택 안 된 항목에 마우스만 올려도 구별되지 않는다. `shadcn add toggle`로 재생성하면 이 값이 되돌아온다.
- **`variant="list"` — 넓은 행이 세로로 쌓인 목록형 선택지**(신고 사유 등)**에만 쓴다.** 이 형태에 솔리드 채움을 쓰면 같은 화면의 primary CTA와 같은 크기·같은 색 덩어리가 둘이 되어 무엇이 액션인지 흐려진다(밝기 예산 규칙 — 화면당 `primary` 솔리드 채움은 하나뿐이어야 한다). 그래서 `border-primary` + `text-primary` + `bg-primary/10` 틴트로만 표시하고(선택 행 텍스트 대비 **5.24:1**), 솔리드 채움은 CTA에 남긴다. **필터 칩 개편(2026-09-11)의 두 변경(pill · 비활성 글자 다운)을 둘 다 받지 않는다** — `lg`(8px)와 `text-foreground`로 남는다. pill을 안 받는 이유는 그 개편이 가르려던 축이 *칩 대 액션 버튼*인데 `list`는 애초에 칩이 아니기 때문이다: 신고 모달의 행은 호출부가 `h-11`로 올려 **352×44px**이라 pill을 주면 반경이 **22px**이 되고, 바로 아래 CTA는 **36px·8px**이라 선택지 쪽이 더 버튼처럼 읽혀 의도가 뒤집힌다(실측). 글자 다운을 안 받는 이유도 같은 뿌리다 — 필터 칩은 이미 뜻을 아는 항목을 반복해서 훑는 자리라 낮춰도 되지만, `list`는 처음 보는 여러 문장을 전부 읽고 하나를 고르는 자리다. 대비 수치가 AA를 넘어도 그게 "읽는 부담이 없다"를 보장하진 않는다.
- **`variant="tab"` — 라우트 전환 탭 하나뿐인 자리에 쓴다**(헤더의 캐릭터/스토리, 그리고 그 옆 "노벨" 링크가 같은 시각을 빌린다 — 밑줄은 `data-[state=on]`에만 걸려 링크도 `data-state="on"`으로 켠다. 노벨 링크는 노벨이 열려 있을 때만 그린다(공개 가격 응답의 켜짐 표시 — 비로그인에게도 보이고, 누르면 로그인으로 갔다가 돌아온다). 홈 첫 행의 캐릭터/스토리 전환도 같은 컨트롤이다 — 1024px 미만에서는 헤더 탭이 드로어 안으로 들어가므로 홈이 그 자리를 본문 첫 행에 다시 세우고, 그 이상에서는 헤더 탭과 겹치지 않게 유형 이름 텍스트만 둔다). **필터 칩에는 쓰지 않는다.** 채움·보더 없음, `relative`(베이스 `toggleVariants`엔 없어 `tab`이 직접 선언 — 없으면 `after:absolute` 밑줄이 포지셔닝 컨텍스트를 상위(헤더)로 흘려 엉뚱한 위치에 찍힌다), `rounded-md`(포커스 링 모양용), 비활성 `text-muted-foreground`, 활성 `text-foreground` + `after:` 의사요소 밑줄(`h-0.5 bg-foreground`, `opacity` 전환, `motion-safe:`). 활성 표시가 `primary`가 아니라 `foreground`인 것은 One-Accent Rule과 `Tabs variant="line"`의 어휘를 그대로 따르는 것이다. **밑줄 위치는 `after:bottom-0`이다 — `tabs.tsx`의 `bottom-[-5px]`를 베끼지 않는다.** 그 −5px는 `TabsList`의 `h-9`+`p-[3px]`와 트리거 `h-[calc(100%-1px)]`가 만드는 **약 3.5px 트로프**를 상쇄하는 값인데(박스모델 계산) `ToggleGroup`엔 그 패딩 트로프가 없다. 36px 아이템이 56px 헤더에 중앙 정렬되면 아래 여유가 10px뿐이라 −5px를 그대로 쓰면 밑줄이 헤더 `border-b`와 3px 거리에서 이중선으로 읽힌다. **밑줄은 헤더 `border-b` 위 11px에 앉는다**(1512·390·320px 스크린샷 확인) — 이중선으로 안 읽힌다. `tab`이 활성 솔리드 채움이 없다는 사실은 포커스 오버라이드 생략과 **직접** 연결된다: 포커스 표시의 하중은 `border border-transparent`가 진다 — `focus-visible:border-ring`이 그걸 불투명 핑크로 바꿔 헤더 배경 대비 **7.18:1**(≥3:1 통과)이 되고, **50% 링 단독은 2.58:1로 미달**이다(실측). `default`/`outline`이 필요했던 **불투명 포커스 링 오버라이드(`data-[state=on]:focus-visible:ring-ring`)가 `tab`엔 필요 없는 이유는 채움이 없어 `border-ring`이 사라지지 않기 때문**이다 — `default` 등에서는 그 보더가 `primary` 채움과 같은 색이 되어 지워졌지만(아래 포커스 링 문단), `tab`엔 채움 자체가 없어 그 문제가 없다. 활성 텍스트 대비는 **15.86:1**(`text-foreground`) / 비활성 **6.74:1**(비활성 칩 값 재사용, 다크 on `background`) — 이전 pill 형태(핑크 채움 위 반전 글자)는 활성 **7.18:1**이었다. **`px-2`는 `variant` 문자열이 아니라 `compoundVariants`로 들어간다**(`{variant:"tab", size:"default", class:"px-2"}`) — cva는 `base + variant + size + compoundVariants` 순으로 이어붙이고 twMerge는 **뒤에 오는 것을 남기므로**, `variant` 문자열에 넣은 `px-2`는 `size.default`의 `px-4`에 **진다**(2026-09-15, 실제 패키지로 확인).
- **감사 테스트:** 토글에 새 선택 표시를 만들려 한다면, 그 항목이 버튼만 한 크기인지 자문하라. 그렇다면 기본 채움을 그대로 쓰고, 한 줄을 가득 채우는 크기라면 `list`를 쓴다.
- **좌측 드로어(Navigation 절)의 캐릭터/스토리 전환은 `variant="tab"`이 아니라 `variant="outline"`인 가로 pill 쌍이고, 그 옆 "노벨" 링크도 같은 `outline` 시각의 pill로 놓인다** — 이 자리에서만 줄 넘김(`flex-wrap`)을 둔다. 드로어 폭(390 화면에서 약 290px, 넓은 화면에서도 `sm:max-w-sm` 384px 상한)에 pill 이 넷(이미지 링크 포함)이던 동안 한 줄에 들어가지 않아 마지막 pill 이 잘렸기 때문이고, 셋이 된 지금도 남겨 둔다. 감사 테스트대로 라벨 3자짜리 버튼 크기라 `list`가 아니라 기본 채움(outline)을 쓴다. `ContentTypeToggle`이 `variant` prop(`"tab" | "outline"`)으로 헤더·드로어 두 자리를 겸한다 — 재클릭 시 `""` emit 가드와 홈 이동을 두 컴포넌트로 복제하면 한쪽이 조용히 새는 실패 모드(17곳 중 2곳만 맞았던 선례와 같은 뿌리)를 반복하기 때문이다. 이동할 search(정렬만 유지하고 나머지 필터는 버린다)는 홈 첫 행의 유형 전환(1024px 미만에만 있는 `tab` 토글)과 함께 `entities/content`의 `toHomeTypeSwitchSearch` 하나가 만든다. 드로어 쪽 호출은 `widgets/header/ui/MobileNavDrawer.tsx`의 `<ContentTypeToggle variant="outline">`이다.
- **`variant="neutral"` — 칩 여러 줄이 한꺼번에 선택돼 있는 자리 전용이다**(지금은 소설 화 읽기 화면의 보기 설정 패널 하나 — 넘김 방식·글자 크기·줄 간격·테마·화면 유지가 한 줄씩이고, 화면 유지 줄은 화면 꺼짐 방지를 지원하지 않는 브라우저에서 빠진다. 좌우 여백은 페이지 모드의 판형 안 고정값이라 설정이 없다). 줄마다 선택된 칩이 하나씩 있어 기본 선택 표시(`primary` 솔리드)를 쓰면 한 화면에 솔리드 채움이 줄 수만큼 생겨 밝기 예산 규칙("화면당 솔리드 하나")을 어긴다 — 그 화면의 솔리드는 화 끝 "다음 화" 버튼 몫이다. 끔/켬 둘뿐인 화면 유지도 같은 이유로 `Switch` 가 아니라 이 칩 둘이다 — `Switch` 의 켬 상태가 `primary` 솔리드다. 선택 표시는 **무채 표면 `secondary` + `border-ring` 윤곽 + `text-foreground`**이고 비선택은 `outline`과 같은 `border-input` + `text-muted-foreground`다. 패널이 `popover` 표면이라 hover는 `muted`가 아니라 `secondary`다(Colors 절 "표면 위 채움" — `muted`는 그 표면과 같은 값이라 사라진다). 선택 칩은 보더가 이미 `ring`이라 포커스 때 `focus-visible:border-ring`이 바꾸는 것이 없어, 선택 칩의 포커스 링은 `default`·`outline`처럼 불투명(`data-[state=on]:focus-visible:ring-ring`)이다. 규칙은 프리미티브(`toggle.tsx`) 안에 있다. **이 variant는 다른 화면으로 번지지 않는다** — 필터 칩·테마 선택처럼 한 줄에 선택이 하나뿐인 자리는 기본 채움을 그대로 쓴다.
- **호출부에 선택 상태 클래스를 직접 붙이지 말 것** — 프리미티브에 없는 규칙을 호출부마다 문자열로 붙이면 새로 추가되는 화면이 조용히 빠진다(실제로 17곳 중 2곳만 맞았던 적이 있다).
- **선택된 토글의 포커스 링은 불투명해야 한다**(`data-[state=on]:focus-visible:ring-ring`). §Buttons의 기본 레시피(`ring-ring/50` + `border-ring`)는 **배경 위에서만** 성립한다 — `primary` 솔리드 채움 위에서는 `border-ring`이 보더를 채움과 **같은 핑크**로 바꿔 rest의 회색 윤곽을 지워 버리고(라이트 **1.0000** / 다크 **1.0437**), 남는 50% 링은 페이지 배경 대비 **2.5757 다크 / 2.5511 라이트**로 WCAG 1.4.11의 3:1에 미달한다(포커스 on/off 픽셀 diff 실측, 두 리뷰어 독립 일치). **이 수치는 포커스가 정착한 뒤 재야 한다** — `transition-all` 0.15s가 box-shadow까지 애니메이션해서 Tab 직후 읽으면 전이 중간값(α≈0.486, 2.4724)이 잡힌다. ToggleGroup은 roving tabindex라 **선택된 칩이 있으면 Tab이 닿는 칩은 언제나 그 칩**이므로 이건 엣지가 아니라 기본 포커스 상태다(선택이 비어 있으면 Radix roving focus가 마지막으로 포커스한 칩, 그것도 없으면 첫 칩으로 보낸다 — 헤더 유형 토글이 이미지 화면에서 그렇다). 불투명 링은 같은 픽셀이 **7.1768 다크 / 6.7011 라이트**가 되고 rest 상태는 1픽셀도 바뀌지 않는다.

### Cards / Containers
- **Corner Style:** radius `xl`(11.2px).
- **Background:** `bg-card`, 테두리 `border-border` 한 줄. **그림자 없음.**
- **Internal Padding:** **콘텐츠 카드(`ContentCard`)에는 껍데기가 없다** — 배경·보더·패딩이 전부 0이고 카드는 `flex flex-col gap-2 rounded-xl` 뿐이다(`rounded-xl`은 focus 링 모양용). 그 밖: 16px(목록형 카드) / 32px(인증 카드).
  - **껍데기를 걷은 이유**는 썸네일이 그 화면의 콘텐츠 자체이기 때문이다 — 레퍼런스 둘(크랙·케이브덕)은 카드에 border·padding·배경이 **전혀 없고** 썸네일이 곧 카드다(실측: `padding: 0px`, `rgba(0,0,0,0)`, 썸네일 `rect.left == 카드 rect.left`).
  - **경계는 카드가 아니라 썸네일이 진다**(아래 Thumbnail well). 텍스트는 썸네일 좌측 가장자리와 flush하게 정렬되고 둘 사이는 `gap-2`(8px)다.
  - **hover 신호를 두지 않는다.** 전엔 카드 표면이 `rgb(13,13,13)→(24,24,24)`(대비비 **1.0946**, 픽셀 실측)로 밝아졌는데 칠할 표면이 사라졌고, **레퍼런스 둘 다 카드 hover가 없다** — 케이브덕은 rest/hover 픽셀이 완전 동일하고 DOM에 `hover:`/`group-hover:`/`transition` 클래스가 0개, 크랙도 카드 스타일이 불변이다(1~2초 머물면 미리보기 팝오버가 뜨지만 그건 별개 기능이다). **터치 피드백인 `active:translate-y-px`는 남긴다** — 그게 유일한 눌림 표시다.
  - focus 표시는 불투명 1px 아웃라인 + 50% 링(`focus-visible:outline-1 outline-ring ring-3 ring-ring/50`, Buttons 절의 Focus — 보더 없는 컨트롤)이고 카드 전체를 감싼다. 50% 링만으로는 3:1 미달이다. 카드에 `overflow-hidden`이 없으므로 잘릴 일도 없다. 홈 큐레이션 카드도 같은 문자열이다.
- **Hover:** `hover:bg-accent/50` — 사다리 위로 반 칸. **단, 이건 정지 표시용 카드에만 유효하다** — 아래 예외를 볼 것. **`ContentCard`는 hover 자체가 없다**(위).
- **예외: 카드 자체가 그 화면의 주 인터랙션이면 button-outline 레시피를 카드 크기로 쓴다** — `border-border bg-background` + `hover:bg-muted` + 하우스 focus 레시피 + `active:translate-y-px`. `bg-card` 위에서는 `hover:bg-accent/50`도 `hover:bg-muted`도 **픽셀상 아무것도 그리지 않기** 때문이다(`background-color`는 층으로 쌓이지 않고 `bg-card`를 대체한 뒤 페이지 배경 위에 합성된다 — 스크린샷 픽셀 실측 **다크 1.0000:1 / 라이트 1.0178:1**). 이 예외를 쓰면 rest에서 카드 채움이 페이지 배경과 같아져 Elevation 절의 명도 사다리를 벗어나지만, 경계는 `border`가 유지하고 hover는 다크 1.0946 / 라이트 1.0902로 실제로 보인다. 대안인 `bg-card` + `hover:bg-secondary`(hover 라이트 1.1239 / 다크 1.1439)는 `muted-foreground` 본문이 그대로면 라이트 4.30:1로 AA에 미달하므로, **hover 때 본문을 `group-hover:text-foreground`로 올리는 경우에만** 쓴다(14.06:1) — 그러면 셋(사다리·hover 가시성·본문 AA)을 동시에 만족한다. 적용처: admin `CountCards`. outline 레시피 적용처: `BuilderTypeSelectPage`·`InquiriesPage`·`NoticesPage`·`MyChatRoomListView`. **`ContentCard`는 2026-09-11에 이 레시피에서 빠져나왔다** — 껍데기를 통째로 걷고 hover를 없앴다(위).
- **Thumbnail well:** `overflow-hidden rounded-xl border border-foreground/10 bg-secondary` + 타입별 비율 클래스. **카드의 경계를 이 웰이 진다** — 카드엔 보더가 없다. **네 모서리 모두** `rounded-xl`이다. 이미지 없으면 `ImageOff` 아이콘을 `text-muted-foreground`로.
  - **비율은 콘텐츠 타입이 정한다** — 캐릭터 `aspect-square`(1:1), 스토리 `aspect-story`(2:3, `globals.css`의 `--aspect-story` 토큰). 클래스 매핑은 `entities/content/ui/cardLayoutClass.ts`가 단일 소스다(카드와 스켈레톤이 같은 삼항을 각자 들고 있으면 스켈레톤 높이가 어긋난다).
  - **보더가 `border-border`가 아니라 `border-foreground/10`인 이유**: 이제 이미지 **위에** 얹히기 때문이다. `border`(다크 oklch 0.300)는 밝은 이미지 위에서 사실상 안 보이고 어두운 이미지 위에서만 보여 **이미지마다 테두리 유무가 갈린다.** 반투명 흰 선은 어느 이미지 위에서도 가장자리로 읽힌다 — Elevation 절의 `ring-1 ring-foreground/10`(떠 있는 팝오버)과 같은 어휘다.
  - **`bg-secondary`인 이유가 바뀌었다** — 전엔 카드의 `hover:bg-muted` 표면과 같은 값이 되는 걸 피하려는 것이었는데, 카드 표면이 사라진 지금은 **페이지 배경(0.160) 위에서 보여야 해서**다(0.260). 썸네일이 아직 없는 초안 카드에서만 보이는 자리다.
  - **`rounded-lg`를 두지 않는다** — 카드의 `rounded-xl`이 `overflow-hidden`으로 썸네일을 직접 자른다. 안쪽에 별도 반경을 두면 border 1px 안쪽 곡률과 어긋난다.
  - **두 비율은 레퍼런스 실측에서 왔다**(2026-09-11): 크랙 캐릭터 표시·원본 **1.000**(400×400, 크롭 0) / 크랙 스토리 표시 0.669·원본 **0.667**(400×600, 크롭 0). 케이브덕은 캐릭터 4:5(0.8)·세계관 **5:4 가로**(1.25)로 갈라 "스토리는 세로"가 업계 합의가 아님을 보여준다 — 크랙 스토리는 웹소설 표지, 케이브덕 세계관은 배경 이미지라서다.
  - **CSS 슬롯은 정확한 2:3이고 생성 치수는 832×1216(=13:19)이다** — 일부러 다르다. 832×1216은 Animagine XL 4.0 권장 버킷이자 NovelAI 기본값이라 학습치 일치를 비율 정확도보다 위에 뒀고, 그 대가로 생성물에서 가로 **2.56%**(832px 중 21.3px)가 잘린다. **`bg-muted`가 아닌 이유**: 웰이 `bg-card` 카드 위(rest)에서도, `hover:bg-muted`가 걸린 카드 위(hover)에서도 표면과 같은 값이 되어 사라진다(둘 다 실측 1.0000:1). `secondary`는 두 상태 모두에서 살아남는다(rest 다크 1.2521 / hover 다크 1.1439).
- **Title:** `ContentCard`의 제목은 `line-clamp-2 break-keep break-words`이고 **2줄 높이를 항상 예약한다**(`min-h-[2lh]`). 실측(2026-09-14): `text-sm`(16px) 줄높이 **22.857px**, 2줄 클램프 박스(=`min-height`) **45.7031px** — 콘텐츠 길이와 무관하게 항상 이 값이다(`min-height`가 바닥을, 클램프가 천장을 같은 지점에서 막는다 — 297px 분량을 주입해도 45.703125px로 실측). 그 결과 `actions`(32px)가 제목 행 높이를 지배하던 구도가 역전되어(32 < 45.7) `actions` 유무가 제목 행 높이에 영향을 주는 경로가 사라졌고, 로딩 스켈레톤이 nbsp 한 줄로도 정확히 같은 높이를 얻는다. `break-keep`과 `break-words`를 **함께** 쓰는 이유: `break-keep` 단독이면 컨테이너보다 긴 단일 어절이 가로로 넘치고 `line-clamp`은 `text-overflow`를 세팅하지 않아 **`…` 없이 글자 중간에서 하드컷된다**(실측 임계: 390px 스토리 열 111.33px에서 9글자, 제목 실폭 71.33px 열에서 6글자). 채팅 본문(`ChatMarkdown.tsx`)도 같은 목적의 쌍을 쓰되 `break-keep wrap-break-word`로 적는다 — 클래스를 `cn()`으로 합치는데 tailwind-merge가 `break-words`와 `break-keep`을 한 무리로 보고 앞의 것을 지우기 때문이다(`twMerge('break-keep break-words')` → `break-words`만 남는다). `ContentCard`는 평범한 문자열이라 둘 다 남는다.
- **카드 그리드의 열 수는 썸네일 비율이 정한다**(`ContentCardGrid`): `square` 2/3/4 · `portrait` **3/4/5** · 섞인 목록 2/3/4 + `items-start`. gap은 셋 다 `gap-3`이다. **첫 줄에 `priority`(eager)를 줄 개수도 같은 비율에서 도출한다**(`entities/content/model/cardLayout.ts`의 `toPriorityCount`) — 손으로 적은 `index < 4`가 사다리 변경을 따라오지 않아 첫 줄 마지막 카드가 lazy로 빠진 적이 있다.
  - **`portrait`이 390px에서 3열인 것은 껍데기를 걷은 결과다.** 패딩이 있던 동안엔 3열이 불가능했다 — 카드 폭 111.33px에서 `p-3`+border를 빼면 텍스트가 85.3px뿐이라 작가명에 **21.9px(한글 1.8자)** 만 남았다. 껍데기가 사라져 텍스트가 카드 폭 **전체**를 쓰면서 근거가 뒤집혔다. **크랙이 390px 3열을 감당하는 조건이 정확히 이것이었다** — 레퍼런스의 수치를 베낄 때는 그 수치를 성립시키는 조건까지 같은지 볼 것.
  - **지표 숫자는 축약한다**(`formatCompactCount`, `46.8K`·`1.2M`). 3열에서는 조회수 자릿수가 작가명을 그대로 잠식한다 — 전체 숫자면 작가명이 `1,234`에서 3.6자, `46,821`에서 2.9자, `1,234,567`에서 **1.3자**로 줄어든다(390px 3열·작가명 7자 기준 canvas 실측). 축약하면 숫자 폭이 5자 안팎에서 고정돼 자릿수와 무관해진다 — 같은 조건에서 `1.2M`은 **4.0자**, `46.8K`는 3.4자다. **크랙도 같은 이유로 `46K`·`4.7M`을 쓴다.** 상세화면은 폭 제약이 없어 전체 숫자를 유지하고, 스크린리더에는 축약이 아니라 **전체 숫자를 읽힌다**(`sr-only`).
  - **섞인 목록에 `items-start`가 필요한 이유**: 없으면 grid 기본 `stretch`가 짧은 카드를 긴 카드 높이까지 늘려 **빈 border 상자**가 생긴다. 실측(2026-09-14, 390px, `/my` 전체 필터, `actions` 있는 카드): 제목 2줄 예약 전 캐릭터 **267.66px** / 스토리 **354.16px** → 예약 후 캐릭터 **281.37px** / 스토리 **367.87px**(둘 다 +13.70px = 45.7−32, `actions`가 더는 제목 행을 지배하지 않기 때문이다). **절대 차이 86.5px는 전/후 동일하므로 결론(`items-start`가 필요하다)은 바뀌지 않는다.** 이 문서의 이전 값(캐릭터 245 / 스토리 331)은 이번 런 전에 이미 한 줄만큼(약 22.7px) 낮았다 — 원인은 문서화되지 않았다. 예약 후 값(281.37/367.87)은 최종 확정 실측이다. 제목 박스 높이는 콘텐츠 길이·뷰포트와 무관하게 항상 **45.703125px**다(390/768/1512px에서 짧은 제목과 2줄 꽉 찬 제목이 동일). **스켈레톤과 실제 카드의 높이가 같다** — 홈의 스토리 카드(`actions` 없음) 기준 스켈레톤 `offsetHeight` 245px 대 실제 카드 `offsetHeight` 245px, 차이 0(실측). 앞의 281.37/367.87px(`/my` 전체 필터, `actions` 있는 카드)와 값이 다른 것은 모순이 아니다 — 화면·props가 달라서다: 카드 높이는 열 폭과 `actions` 유무에 따라 달라진다. **한 행의 카드들 조회수 줄 `top`이 정렬된다**(Δ ≤ 0.008px, 서브픽셀 반올림뿐). **잘림 건수 실측**: 시드 스토리 제목 30건 중 390px **24** · 640px **6** · 768px **8** · 1024px **0**(현행 1줄에서는 390/640/768 전부 30건이었다) — 예측과 정확히 일치했다. `min-h-[2lh]`의 computed `min-height`가 **45.7031px**임을 확인했다(`lh` 단위가 동작한다).
- **Empty state:** `rounded-xl border border-dashed border-border py-16` — 점선은 보여 줄 내용이 없는 자리에 쓴다: 빈 상태(같은 셸을 쓰는 불러오기 실패 상태 포함), 아이콘·컬러 피커의 빈 자리표시, 미디어 북의 빈 칸. 예외로 엔딩·상황 노트 안의 규칙 그룹 카드는 내용이 있어도 점선이다 — 바깥 항목 카드와 구별하려는 것이다(Builder repeated items 절의 규칙 그룹 항목).

### Media images (글 속 그림 · 보관함 칸 · 배치표 칸 · 이미지 넣기 모달 칸 · 칸 상세 미리보기 · 폰 화면 캡처 틀)
미디어 북 이미지가 서는 자리 다섯과, 서비스 소개 화면의 캡처 틀 하나다. 모두 **이미지가 오기 전에 자리 높이를 잡는다**(비율을 모르는 원격 이미지는 웰 먼저 — 도착하는 순간 읽던 글이 밀리면 안 된다).

- **글 속 그림 블록**(`shared/ui/media-image-frame/MediaImageFrame.tsx`) — 채팅 첫 메시지·에필로그, 상세의 등록 설명·펼친 프롤로그, 채팅 판정 이미지가 같은 틀을 쓴다. 문단 사이 블록이고(`self-start`, `rounded-lg`, 보더·그림자 없음), 그림은 크롭 없이 `object-contain`이다.
  - **최대 높이 320px · 본문 폭 캡.** 크기를 알면 `aspect-ratio: w / h`에 폭을 "높이가 320에 닿는 폭"(`round(320 × w / h)px`)으로 못박고 `max-width: 100%`로 컬럼에 맞춰 줄인다 — 세로 3:4는 240×320, 정사각은 320×320, 16:9는 569×320(좁은 컬럼에서는 폭에 맞춰 줄고 높이는 비율이 정한다). 320은 크기를 모르는 그림의 고정 웰(`h-80`)과 같은 값이라 두 갈래가 같은 키로 서서 대화 리듬이 갈리지 않는다. 높이 상한 없이 컬럼 폭만 두면 세로 그림이 데스크톱 본문 폭(768px)에서 1024px 높이의 밝은 면이 된다 — 밝기 예산 규칙과 어긋난다.
  - **캡은 높이가 아니라 폭에 건다.** `aspect-ratio`에 `max-height`를 걸면 폭이 줄지 않는다. 폭을 퍼센트(`w-full`)로 두지 않는 것은 채팅 본문 상자가 내용 폭만큼만 차지하는(shrink-to-fit) 상자라 퍼센트 폭이 그림 도착 전 0으로 계산되어 틀이 납작해지기 때문이다.
  - **크기를 모르면 고정 3:4 웰**(`aspect-3/4 h-80 max-w-3/4`) — 크기를 기록하기 전 자산과 캐릭터 상황별 이미지가 이 갈래다.
  - **면**: 페이지 배경 위는 `bg-muted`, 다이얼로그·`secondary` 상자 안은 `bg-secondary`(`surface` prop, 기본값 없음 — Colors 절의 "표면 위 채움 규칙").
  - **확대 보기 없음.** 320px이 이미 본문 폭에 가깝고, 탭 확대는 모달·포커스 관리·전환 모션을 새로 들인다. 서명된 원본 주소를 새 탭으로 여는 방식은 만료되는 주소를 주소창·방문 기록에 남긴다.
  - **접히는 글에는 그림을 넣지 않는다** — 상세 프롤로그의 접힌 요약(`line-clamp-4`)은 태그를 뺀 글만 보여 주고, 펼치면 그림이 제자리에 선다. 줄 수 자르기는 줄 상자 단위라 블록 그림이 들어가면 그림 하나가 요약을 다 먹거나 잘린 채 보인다.
- **보관함 칸**(스토리 채팅 더보기 → 이미지 보관함, 다이얼로그) — 인물별 묶음, `grid-cols-2 sm:grid-cols-3 items-start gap-2`. 칸 틀은 크기를 알면 원본 비율, 모르면 3:4이고 그림은 `object-cover`, 빈 칸 면은 다이얼로그 위라 `bg-secondary`다. `items-start`는 비율이 다른 칸이 한 줄에 설 때 짧은 칸을 늘려 그림 아래 빈 면이 생기지 않게 한다.
  - **잠긴 칸 = 토큰 글자 + 반투명 배경 면.** 서버가 준 블러본 위 가운데에 `bg-background/75 rounded-md` 면을 **글자 둘레에만** 깔고 `text-foreground` 자물쇠(16px)와 해금 힌트(`text-xs break-keep`)를 얹는다. 면을 칸 전체에 깔지 않는 것은 흐린 그림이 남아 보이게 하려는 것이다. 힌트가 비면 같은 면에 자물쇠만 남는다. 스크림 쌍이 아니라 테마 쌍을 쓰는 이유와 대비 수치는 Colors 절 Tertiary의 "테마 쌍 면"이다. `text-white`나 옅은 그라데이션 스크림은 쓰지 않는다.
- **배치표 칸**(빌더 미디어 북 탭, `widgets/build-story/ui/MediaBookGrid.tsx`) — 표는 폼 열이 아니라 **미리보기 자리**에 선다: 1024px 이상에서는 오른쪽 열이 대화 미리보기 대신 배치표를 보이고(대화는 숨겨 둔 채 마운트를 유지한다), 그 미만에서는 상단 '배치표' 버튼으로 여는 미리보기 화면이 배치표다. 두 폭을 묶음 한 벌(`widgets/build-story/ui/MediaBookGridPane.tsx` — 진척 한 줄 + 표, 인물·장면이 없으면 빈 상태)이 맡는다 — 두 벌이면 칸 버튼을 찾는 선택자가 숨은 쪽을 잡는다. 고른 칸의 상세는 폼 열에 남아 넓은 화면에서는 표와 나란히 선다. 열은 인물, 줄은 장면, 장면 이름 열은 `sticky`로 고정하고 인물이 많으면 표만 가로로 밀린다(`overflow-x-auto` + 포커스 링 상쇄 `-m-1 p-1`) — 미리보기 열이 좁은 1024px 부근에서는 인물 몇 명만으로도 밀리는 것을 받아들였다. 칸은 **80px 고정**(`size-20`)이고 그림은 원래 비율대로 칸 안에 `object-contain` — 칸 크기가 그림과 무관해 그림이 도착해도 표가 움직이지 않는다.
  - 채운 칸 `border border-foreground/10 bg-muted`, 빈 칸 `border-dashed border-input` + `Plus`(`text-muted-foreground`, hover 시 `bg-muted`). 고른 칸은 채움이 아니라 `border-2 border-solid border-ring`(강조색 실선) — 썸네일이 칸을 덮어 채움은 보이지 않고, 무채색 테두리는 밝은 그림 가장자리에서 묻힌다. 포커스(하우스 레시피)와는 바깥 반투명 링 유무로 갈려 둘이 겹쳐도 각자 보인다. 바깥으로 띄운 링은 쓰지 않는다 — 첫 인물 열에서 고정된 장면 이름 열의 배경 채움 밑에 깔린다.
  - 그림 위 표식 둘은 테마와 무관한 스크림 쌍(`bg-scrim/70 text-scrim-foreground`)이다 — 왼쪽 위 대화 제외 표식(`EyeOff`), 왼쪽 아래 상황 설명 없음 표식(`PenLine` — 이미지는 있는데 설명이 공백뿐인 칸, "다음 미완성 칸" 이 도는 칸과 같은 판정). 둘 다 20px이고 같은 정보를 칸 버튼의 접근 이름이 함께 싣는다. 칸마다 표기 복사 버튼을 얹지 않는다 — 채운 칸 수만큼 같은 아이콘이 그림 위에 반복되고 칸마다 탭 정지가 둘이 된다. 표기 복사는 칸 상세 머리에 하나만 두고, 표기가 무엇에 쓰이는지 한 문장을 곁들인다.
  - 진척은 표 위 한 줄 하나가 말한다(`N칸 중 M칸 채움 · 상황 설명 없는 칸 K`). 탭 머리에 이미지 장 수/상한을 따로 두지 않는다 — 같은 장 수에 분모가 둘 서면 상한을 채워야 할 칸 수로 읽힌다. 상한은 표의 칸이 상한보다 많을 때(그때만 다 채울 수 없다) 같은 줄에 붙는다.
  - **칸에 이미지 파일을 끌어다 놓으면 그 칸을 채운다**(브라우저가 파일 끌기를 지원하는 곳이면 어디서든 동작한다 — 데스크톱과 iPad Safari 처럼. 대부분의 휴대폰 터치 화면에는 파일을 끌어 올 길이 없다). 칸 상세의 '파일 올리기'와 같은 길(같은 형식·크기 검사와 안내 문구, 채운 칸이면 확인 없이 바꾸고 같은 되돌리기 토스트)이고, 다 올리면 그 칸을 골라 상세에 띄운다 — 올리는 동안 사용자가 다른 것을 누르거나 입력했으면 고르지 않는다. 한 번에 여러 장을 놓으면 넣지 않고 '파일 이름으로 한꺼번에 넣기'로 안내한다(끌어온 파일의 순서는 사용자가 알 수 없어 "첫 장"을 정할 수 없다). 파일을 끄는 동안만 칸이 포커스와 같은 문법(`border-ring` + `ring-3 ring-ring/50`, 빈 칸은 hover 면 `bg-muted`)으로 놓을 자리를 보이고 전환 모션은 없다. 올리는 중에는 빈 칸의 `Plus` 자리, 채운 칸은 가운데 스크림 쌍(`bg-scrim/70`) 위에 스피너가 선다(진행 표시라 모션 가드 예외). 칸이 아닌 자리(칸 사이·이름 머리·빈 상태)에 놓으면 묶음이 "놓을 수 없음"으로 받아 브라우저가 파일을 여는 것을 막는다.
  - 묶음은 면을 깔지 않는다 — 미리보기 열의 `background` 그대로라 sticky 장면 열의 `bg-background`가 열 면과 같고(가로로 밀어도 뒤로 칸이 비치지 않는다) 채운 칸 웰 `bg-muted`가 사라지지 않는다.
- **이미지 넣기 모달 칸**(글 입력칸 옆 "이미지 넣기", `features/edit-media-book/ui/MediaTagPickerModal.tsx`) — 그림이 있는 칸만 인물별로 묶어 `grid-cols-3 gap-2` 로 늘어놓는다. 웰은 `aspect-square rounded-lg bg-secondary` 이고 그림은 `object-contain` 이다 — 모달(`popover` 표면) 안이라 `muted` 는 사라지고, 고르는 기준이 그림 전체라 자르지 않는다. 주소가 없는 칸은 같은 웰에 `ImageOff`(`text-muted-foreground`). 웰 아래에 장면 이름(`text-xs truncate text-foreground`), 버튼의 접근 이름은 `인물 / 장면` 이다.
- **칸 상세 미리보기**(`widgets/build-story/ui/MediaBookCellPanel.tsx`) — 두 크기다. 머리의 썸네일은 48px(`size-12 rounded-md border border-foreground/10 bg-muted`, `object-contain`)로, 좁은 화면에서 표가 다른 화면에 있어도 어느 칸인지 이름과 함께 알려 준다. 상세는 폼 열(인물·장면 목록 아래)에 서고, 칸을 고르기 전에는 같은 윤곽의 자리표시가 그 자리를 지킨다. 좁은 화면에서는 칸을 고르면 배치표 화면이 닫히고 상세로 넘어오며, 머리의 `lg:hidden` 뒤로 버튼('배치표로 돌아가기')으로 표에 돌아간다. 칸을 고르면 폭·입력 방식과 무관하게 포커스가 상세 제목으로 오고(닫으면 표가 옆 열에 보이는 넓은 화면은 표의 그 칸으로, 좁은 화면은 자리표시의 '배치표에서 칸 고르기' 버튼으로 간다), 상세의 버튼은 터치에서 40px(`pointer-coarse:h-10`)이다. 빈 칸이면 같은 크기의 상자가 `border-dashed border-input` + `ImageOff` 다. 본문 미리보기는 긴 변 상한 세로 256px · 가로 192px — 크기를 알면 원본 비율 상자, 모르면 3:4 상자에 `object-contain` 이고, 상자가 그림 도착 전에 정해져 아래 입력칸이 밀리지 않는다. 상세는 채움 없는 윤곽 상자라 두 웰 모두 `background` 위의 `muted` 다. 확대 보기는 없다(글 속 그림 블록과 같은 이유).

- **폰 화면 캡처 틀**(`/about`의 기능 소개, `pages/about/ui/AboutPage.tsx`) — 저장소에 함께 든 실제 화면 캡처(390×844 CSS를 배율 2로 뜬 다크 테마 WebP)를 기능 설명 옆에 세운다. 위 다섯과 달리 원격 이미지가 아니라 번들 자산이라 크기를 언제나 안다.
  - **폭 고정, 높이는 비율.** 틀 폭은 256px(`w-64`), `md` 이상 288px(`md:w-72`)이고 `<img>`에 실제 픽셀 `width`·`height`를 주어 브라우저가 그림 도착 전에 비율(세로 캡처 390:720, 클로버 미션 390:435)만큼 자리를 잡는다 — 자리 이동 0. 폭 캡은 세로로 긴 폰 화면이 좁은 화면을 통째로 덮지 않게 하려는 것이다(256px 폭이면 세로 캡처가 약 470px).
  - **틀**: `overflow-hidden rounded-xl border border-foreground/10 bg-muted`, 그림자 없음. 반경은 카드 티어(`rounded-xl`)에서 멈춘다 — 기기 모서리를 흉내 내는 더 큰 반경은 이 시스템에 없는 값을 새로 들인다. 캡처가 다크 테마라 라이트 배경 위에서는 어두운 사각형으로 서는데, 1px 보더가 그 가장자리를 우연이 아닌 틀로 읽히게 한다. `bg-muted`는 페이지 배경 위의 웰이라 그림이 오기 전 빈 자리다.
  - **로딩**: 첫 캡처만 `eager`(소개문 바로 아래 첫 화면 범위), 나머지는 `lazy`. 모두 `decoding="async"`, `fetchPriority`는 주지 않는다.
  - **배치**: `md` 미만은 글 → 그림 한 열(그림 가운데 정렬), `md` 이상은 글 | 그림 두 열(`md:flex-row md:items-center`). 그림은 늘 오른쪽이고 DOM 순서는 언제나 글이 먼저다. 이 두 열은 `<main>` 안의 콘텐츠 배치라 Navigation 절의 크롬 금지 대상이 아니다.

### Inputs / Fields
- **Style:** radius `lg`(8px, §반경 정책 — `Input`은 36px 티어), `border-input` 테두리, 투명 배경. **이 테두리는 장식이 아니라 컨트롤 식별자다** — 채움이 배경과 같아 이 한 줄이 없으면 필드가 존재하지 않는다. 값은 Colors 절 Neutral의 `input`(구분선 `border`와 다른 값)이고 3:1을 진다.
- **Focus:** `ring-3 ring-ring/50` + `border-ring` — 버튼과 동일한 포커스 언어.
- **Error:** `aria-invalid`에 `border-destructive` + `ring-destructive/20`. 에러 텍스트는 Label 크기 + `text-destructive-text`(글자는 텍스트 전용 토큰, 보더·링은 `--destructive`).
- **Required:** 필수 라벨은 글자 뒤 띄어쓰기 한 칸 + 별표이고, 별표만 `text-destructive-text`다(`apps/web/src/shared/ui/RequiredText.tsx`). 빨강이 오류 전용이라는 원칙의 예외로 사용자가 고른 관례다 — 별표 한 글자에만 걸리고 라벨 글자나 다른 강조로 번지지 않는다. 별표는 숨기지 않아 접근 이름에 "*"가 남는다. **예외는 빌더 탭 줄의 별표다** — 언제나 필수인 탭(빈 초안이 발행 검증에서 오류를 내는 탭) 이름 뒤에 같은 빨간 별표를 붙이되 별표는 `aria-hidden`이고 화면 밖 글자 "(필수)"를 함께 둔다. 탭 역할에는 필수를 알릴 상태(`aria-required`)가 없어 이름 글자로 전해야 하는데, "*"는 읽기 설정에 따라 "별표"로 읽히거나 아예 빠져 필수라는 뜻이 전해지지 않기 때문이다. 오류가 있는 탭은 별표와 "(필수)" 대신 오류 표시만 둔다(`apps/web/src/features/build-common/ui/BuilderTabStrip.tsx`).
- **Character count:** 글자 수 한도가 있는 빌더 칸은 입력칸 바로 아래 줄 오른쪽에 `n/최대`(`text-xs tabular-nums` `muted-foreground`, 화면 밖 접두 "글자 수", 입력칸의 `aria-describedby`)를 두고 그 줄 왼쪽은 도움말 자리다(`apps/web/src/features/build-common/ui/CharacterCount.tsx`). 셈은 서버와 같은 코드 포인트이고 앞뒤 공백도 센다. 상한에 닿으면 숫자를 `font-medium` + `foreground` 로 올린다 — 꽉 찬 것은 오류가 아니라 경고색을 쓰지 않는다. 상한을 넘은 값이면 숫자가 `destructive-text` 다. 값을 바로 폼에 쓰는 칸은 `maxLength` 대신 입력할 때 넘친 만큼을 방금 넣은 글에서 덜어내고(꽉 찬 글 중간에 붙여넣어도 원래 글의 끝은 지우지 않는다, 한글 조합 중에는 자르지 않고 조합이 끝날 때 자른다) 그 순간 도움말 자리에 "N자까지 들어가요. 넘친 글자는 넣지 않았어요."를 알린다(`useLimitedTextField`). 넣거나 반영할 때 검사하는 칸(칩 입력·미디어 북 이름)은 자르지 않고 넣을 때 이유와 함께 거절한다.

### Builder repeated items (빌더 반복 항목 접기)
빌더의 반복 항목은 전부 같은 접기 카드(`features/build-common/ui/CollapsibleItemCard.tsx`)에 담긴다 — 스토리의 시작설정·스탯·상황 노트·엔딩(+ 엔딩·상황 노트 안 규칙 그룹)·키워드북 노트·단축어·전개 예시, 캐릭터의 예시 대화·상황별 이미지. 긴 항목 몇 개가 화면을 다 먹어 목록 전체를 훑을 수 없던 것을 푸는 패턴이다.

- **머리 줄은 접힘·펼침 어느 쪽이든 같은 자리·같은 모양이고 상세는 그 아래로 펼쳐진다.** 카드 `flex flex-col gap-4 rounded-xl border border-border bg-background px-4 py-3`, 머리 줄 `flex items-center gap-2` = [순서 손잡이 `ItemDragHandle`(순서를 바꿀 수 있는 목록만)] · [토글] · [삭제 `ItemRemoveButton`]. 손잡이는 포인터로 끌거나, 포커스한 채 위·아래 화살표 키로 한 칸씩 옮긴다 — 옮긴 뒤에도 포커스가 그 손잡이에 남고 "N번째로 옮겼어요"를 읽힌다(`features/build-common/lib/useSortableList.ts`). 펼칠 때 바뀌는 것은 머리 줄 아래 본문의 표시 여부뿐이라 머리 줄의 top·left·높이가 두 상태에서 같다(브라우저 실측).
- **토글은 버튼 하나다**(`features/build-common/ui/CollapsibleItemToggle.tsx`, `<button aria-expanded aria-controls>`) — 제목·요약·오류 표시·셰브런을 함께 담는다. 손잡이와 삭제는 그 안이 아니라 **형제**다: 버튼 안의 버튼은 무효 HTML이고, 넣더라도 안쪽 버튼의 클릭(포인터·Enter·Space 모두 클릭을 낸다)이 토글까지 올라가 함께 눌린다. 머리 줄 전체를 누르는 영역으로 만들지 않는 이유도 이것이다.
- **제목은 읽기 전용이다** — 그 항목의 이름 값이고(키워드 노트는 이름이 비면 첫 트리거 키워드), 비면 흐린 자리표시(`text-muted-foreground font-medium`)를 보인다: 이름 있는 목록은 `새 스탯`·`새 엔딩`류, 이름 필드가 없는 목록은 `전개 예시 N`·`예시 대화 N`·`상황별 이미지 N`, 규칙 그룹은 고정 제목 `규칙 그룹`. 이름을 고치는 입력칸은 **펼친 본문 맨 위**에 있다. 같은 이름 항목이 여럿일 때를 위해 토글 이름 앞에 화면에 안 보이는 순번(`2번째 스탯: `)을 붙이고, 삭제 버튼 이름은 `<이름> 스탯 삭제`(이름이 비면 `N번째 스탯 삭제`)처럼 항목을 가른다.
- **요약**은 제목 오른쪽 `text-xs text-muted-foreground` 한 줄이고 남는 폭만 써서(기준 폭 0) 좁아지면 제목보다 먼저 잘린다. 구분자는 ` · `, 비어 있는 재료는 빼서 빈 구분자를 남기지 않는다(예: 스탯 `[아이콘][색 점] 0~20일 · 초기 20 · 턴당 -1`·`[아이콘][색 점] 0~100 · 초기 20 · 규칙 3개` — 단위는 범위에만 붙인다, 엔딩 `10턴 이후 · 규칙 2개`, 미디어 북 섹션 `도희 · 유나 · 세빈`). 요약은 토글 이름에 들어가 접힌 상태도 스크린리더가 읽는다 — `aria-hidden`은 아이콘 글리프·색 점 같은 장식에만 건다. 스탯의 색 점은 사용자 콘텐츠 색(스탯 스와치)이다. 스탯 요약은 좁아지면 범위를 남기고 뒤에서부터(규칙 수 → 턴당 변화 → 초기값) 잘린다 — 범위는 줄어들지 않는 조각이고 나머지는 한 줄 글이라 말줄임이 끝부터 먹는다.
- **접힌 본문은 언마운트하지 않고 `hidden`으로 숨긴다.** 언마운트하면 폼 등록·마운트 집합이 펼친 적 있는 항목에 따라 갈려 자동저장 본문이 달라질 수 있고(값이 비어 있던 필드는 처음 붙을 때 빈 문자열이 써진다), 쓰다 만 칩 입력·업로드 미리보기 같은 항목 안 state가 접을 때마다 사라진다. 본문은 제목을 이름으로 하는 `role="group"`이다 — 항목마다 `region`이면 목록이 길 때 랜드마크가 수십 개가 된다. 카드·본문에 `overflow-hidden`을 두지 않는다(본문 안 피커 패널·선택 목록이 잘린다).
- **열고 닫는 데 전이 애니메이션이 없다** — 셰브런도 `rotate-180`으로 즉시 뒤집힌다. `hidden`은 높이 전이를 걸 수 없고, 어두운 방에서 갑작스러운 움직임은 놀람이다(Motion 절).
- **열림 규칙**: 빌더 화면에 처음 들어오면 기존 항목은 모두 접혀 있다. '추가'로 만든 항목은 펼친 채 이름 칸(이름이 없는 목록은 첫 칸)에 포커스가 간다 — 추가 핸들러가 `append`보다 먼저 같은 핸들러에서 열림을 기록해야 새 본문이 처음부터 보이는 채로 커밋되고 포커스가 숨은 칸에 헛걸리지 않는다. **발행이 실패하면 오류가 있는 항목을 펼치고, 오류가 풀려도 펼친 채 둔다** — 셸이 첫 오류로 포커스를 보내기 직전에 그 항목들을 열림으로 *기록*한다. "오류가 있으면 열림"으로 렌더에서 파생하지 않는 이유: 발행 뒤에는 입력마다 다시 검증되므로 오류를 고치는 키 입력 한 번에 항목이 접히고 포커스가 `<body>`로 떨어진다. 오류 경로는 탭 단위로 걸러 스탯·상황 노트·엔딩 오류가 그 위 시작설정 카드까지 열지 않고, 대신 셸이 세 탭이 함께 보는 '고른 시작설정'을 오류가 있는 쪽으로 바꿔 둔다. 머리 줄의 오류 표시(`TriangleAlert` `text-destructive-text` + 화면에 안 보이는 "입력 오류가 있어요")는 표시일 뿐 펼침과 무관하다. 서버 거절이 배열·섹션 자리만 가리키면 열 항목이 없어 목록 머리의 오류 문장이 맡는다.
- **열림 상태는 빌더 화면 안에서만 기억한다** — 탭을 오가도 펼쳐 둔 대로이고 페이지를 떠나면 초기화된다. 셸이 하나 쥐고 컨텍스트로 내리는 외부 저장소다(`features/build-common/model/builderUiState.ts`, `useSyncExternalStore`). 탭 본문은 탭을 바꿀 때 언마운트돼 탭 안 state로는 기억할 수 없고, 셸 state로 두면 항목 하나를 펼칠 때마다 셸과 미리보기가 다시 그려진다. 폼 값이 아니라 토글·선택은 자동저장을 일으키지 않는다(실측 PATCH 0). 키는 목록 이름 + **폼 값의 `id`**다 — RHF `field.id`는 마운트마다 새로 생겨 못 쓰고, 부모 배열 인덱스를 넣지 않아 시작설정 순서를 바꿔도 그 아래 스탯·엔딩의 열림이 유지된다. 값 id가 없는 전개 예시만 인덱스 키이고, 지울 때 뒤 항목의 열림을 한 칸씩 당긴다.
- **삭제 전에 포커스를 옮긴다** — 다음 항목의 토글, 없으면 이전 항목의 토글, 그것도 없으면 그 목록의 추가 버튼(`features/build-common/lib/focusNeighborToggle.ts`). 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 `<body>`로 떨어진다. 확인 모달을 거치는 삭제(엔딩·상황 노트 조건이 걸린 스탯, 스탯·엔딩을 품은 시작설정)는 취소면 누른 삭제 버튼으로, 지웠으면 같은 이웃으로 돌아간다. 나머지는 묻지 않고 바로 지운다. 그중 스탯·엔딩·키워드북 노트·단축어·예시 대화·상황별 이미지는 "‘이름’ 엔딩을 지웠어요 · 되돌리기" 토스트(8초, 미디어 북 칸 이미지 되돌리기와 같은 길이·같은 버튼 — 모두 `features/build-common/ui/UndoToastButton.tsx` 를 쓴다)로 같은 값·같은 자리에 되살릴 수 있다 — 머리 줄의 삭제 버튼이 펼치기 버튼 바로 옆이라 잘못 누르기 쉽고 지운 결과는 곧바로 자동저장된다(상황 노트·전개 예시·규칙, 스탯·엔딩이 없는 빈 시작설정은 되돌리기 없이 바로 지운다). 토스트는 삭제마다 따로 뜬다 — 지우면 아래 카드가 올라와 같은 자리에 다음 삭제 버튼이 서서 연달아 지우기 쉬운데, 토스트 하나를 덮어쓰면 앞의 삭제는 되돌릴 길이 없어진다. 자리는 지울 때 바로 앞에 있던 항목 뒤(그것도 지워졌으면 그 앞)이고, 연달아 지운 것끼리는 아직 되돌릴 수 있는 앞선 삭제를 제자리에 둔 순서로 기억해 어떤 차례로 되돌려도 지우기 전 순서로 돌아온다(`features/build-common/model/removalOrder.ts`). 한 목록 안의 삭제·되돌리기 흐름은 `features/build-common/model/useUndoableRemoval.tsx` 하나이고, 시작설정을 건너 다니는 스탯만 자기 흐름(`widgets/build-story/model/restoreRemovedStat.ts`)으로 그 순서 규칙을 쓴다. 되살린 값은 지운 값 그대로라 폼 값의 id(열림 키)가 같고, 필드 배열에 그 자리로 끼워 넣어 뒤 항목의 입력 오류도 한 칸씩 함께 밀린다 — 오류는 원래 항목에 남고, 되살린 항목 자신은 오류 없이 돌아와 다음 발행 때 다시 검사된다. 지운 뒤 새 항목을 추가해 개수 상한이 찼으면 되돌리지 않고 그 이유를 토스트로 알린다 — 상한을 넘은 목록은 서버가 초안 저장을 통째로 거절한다. 키워드북 노트는 상시 노트만 꽉 찼으면 상시를 끈 채 되살리고 그렇게 했다고 알린다. 상황별 이미지는 되살리면서 그림을 서버 행에 다시 등록한다 — 지운 뒤 자동저장이 지나갔으면 서버가 그 행을 지웠고, 같은 id 로 다시 만들 때는 그림이 비기 때문이다. 노출할 상황이 비어 있으면(등록 API 가 빈 상황을 받지 않는다) 등록을 미루고 "노출할 상황을 쓰면 되돌린 이미지가 다시 연결돼요"라고 알린 뒤 상황 칸을 떠날 때 등록하며, 그 전에 탭을 떠나면 '이미지 없음'으로 돌린다. 다시 등록하지 못하면 그 항목을 '이미지 없음'으로 돌리고 다시 올리라고 알린다. 토스트는 sonner 기본대로 최근 셋까지 겹쳐 보이고(마우스를 올리면 펼쳐진다) 그보다 오래된 것은 보이지 않으며, 각자 8초가 지나면 그 삭제는 확정된다. 되살리면 그 항목의 토글로 포커스가 가고(스탯은 그 스탯이 있던 시작설정이 골라진다, 예시 대화는 '고급 설정' 스위치가 꺼져 있으면 켠다), 다시 끼운 카드 때문에 브라우저 스크롤 앵커링이 스크롤을 옮겨(보이던 다른 항목을 제자리에 두려고) 그 머리 줄이 화면 밖으로 나가면, 부드러운 스크롤 없이 가장 가까운 끝으로 들인다 — 이미 보이면 더 옮기지 않는다. 펼침도 지우기 전 그대로다. 토스트는 그 목록을 떠나면 닫힌다 — 탭을 바꿀 때, 엔딩은 시작설정을 바꿀 때도(엔딩 목록이 다시 마운트돼 지울 때의 목록이 없어진다. 스탯은 시작설정 너머로 되살리므로 탭을 떠날 때만 닫힌다). 확인 모달을 거친 삭제에는 되돌리기가 없다 — 함께 지운 엔딩·상황 노트 조건까지 사용자가 보고 확정했다.
- **표면·포커스·터치**: 카드는 `bg-background`이고 토글 hover는 `secondary`다 — 토글이 앉는 면(항목 카드·규칙 그룹의 점선 카드·미디어 북 섹션)이 모두 `background`인데, 그 위에서 `muted`는 다크 1.0946 / 라이트 1.0902:1로 hover가 거의 보이지 않았다(`secondary`는 Colors 절의 표면 위 채움 규칙과 같은 토큰). 채움 위의 흐린 글자(요약·자리표시 제목)는 hover 동안 `group-hover:text-foreground`로 올린다(라이트 `muted-foreground` on `secondary`는 AA 미달). 토글·손잡이는 맨 `<button>`이라 하우스 포커스 레시피를 직접 건다 — `border border-transparent` → `focus-visible:border-ring` + `ring-3 ring-ring/50`. 50% 링만으로는 3:1에 못 미쳐 1px 보더가 그 몫을 진다. 터치 화면(`pointer-coarse:`)에서는 토글·손잡이·삭제가 36px에서 40px로 커지고 머리 줄도 함께 40px가 된다. 스탯 본문의 아이콘·색 피커 트리거도 같은 규칙으로 40px다. 손잡이가 없는 카드에서는 토글이 `-ml-2`로 당겨져 제목 글자가 본문 입력칸 왼쪽 끝과 맞는다.
- **규칙 그룹**은 엔딩·상황 노트 본문 안에 중첩된 같은 카드이고 `rounded-lg border-dashed px-3`로 덮어 바깥 카드와 구별한다 — 이 점선은 이 패턴 이전부터 있던 규칙 그룹의 모양을 유지한 것이다.
- **미디어 북 인물·장면 목록은 항목이 아니라 섹션째 접는다**(`features/build-common/ui/CollapsibleSection.tsx`, `widgets/build-story/ui/MediaBookAxisList.tsx`). 카드 껍데기 없이 같은 토글을 쓰고(`-mx-2`로 hover 면이 글자 바깥으로 나간다), 제목은 `인물 3`(0개면 `인물`), 요약은 이름 나열이다. 항목이 있으면 기본으로 접혀 칸 상세가 한꺼번에 넣기와 머리 줄 둘 바로 아래에 선다. 이름 추가·수정·삭제는 펼쳐서 한다. **두 섹션은 모든 폭에서 위아래로 쌓인다**(`flex flex-col gap-4`) — 나란히 두면 반 폭 머리 줄에서 이름 나열이 몇 개 못 가 잘리고, 한쪽만 펼치면 두 열 높이가 어긋나 칸 상세가 긴 쪽 아래로 밀린다. **목록이 비었거나 저장되지 않은 이름 오류가 있는 줄이 있으면 섹션은 펼친 채 접을 수 없다** — 빈 목록이면 새 이름 입력칸이 곧 보여야 하고, 오류가 있으면 그 입력칸과 오류 문장이 숨으면 안 된다. 두 경우의 머리 줄은 다르다. **빈 목록이면 버튼이 아니라 제목 글자뿐이다**(토글과 같은 높이·글자 위치) — 누를 것이 없는 버튼은 쓸모없는 Tab 정지점이 되고 스크린리더에 "사용할 수 없는 펼침 버튼"으로 읽힌다. 이 머리 줄에 포커스가 있는 채 목록이 비는 길은 없다(마지막 줄은 지우기 버튼으로만 지우고, 지우면 포커스가 새 이름 입력칸으로 간다). **오류로 잠글 때는 토글을 다른 요소로 바꿔 그리지 않고 같은 버튼에 `aria-disabled`만 건다**(클릭 무시, hover 면·셰브런 없음). `disabled`를 붙이거나 요소를 바꾸면 줄 이름의 blur 커밋이 오류를 세우는 바로 그 순간 Shift+Tab으로 오던 포커스가 `<body>`로 떨어진다. 첫 항목을 추가하는 핸들러가 섹션 열림을 함께 기록해, 0개→1개로 잠금이 풀리는 순간 섹션이 접히지 않는다.

### Menus / Popover lists (드롭다운 · 셀렉트 · 자동완성)
- **포커스 표시는 채움이 아니라 링이 진다** — `focus:inset-ring-1 focus:inset-ring-ring`, `bg-accent`는 보조로 남긴다. 채움만으로는 못 고친다: 포커스 배경(`accent`)이 팝오버 표면 대비 **1.1439 다크 / 1.1239 라이트**(destructive 항목은 `bg-destructive/10`이라 1.1119 / 1.1598)이고, **사다리 최상단 `border`를 채움으로 써도 약 1.3**이다. 링은 팝오버 대비 **6.5567 / 6.1465**, 포커스 채움 대비 중립 **5.7320 / 5.4691** · destructive **5.8968 / 5.2997**이다.
- **링 색은 variant별로 가르지 않는다** — 하나(`ring`)로 중립·destructive 둘 다 3:1을 넘기므로, 한 메뉴 안에서 포커스 어휘가 갈릴 이유가 없다. 심각도는 링이 아니라 글자·글리프 색(`destructive-text`)이 진다.
- **이 규칙은 팝오버 리스트 전체에 건다** — `DropdownMenuItem`(default·destructive)·`CheckboxItem`·`RadioItem`·`SubTrigger`·`SelectItem`, 그리고 손으로 만든 옵션 리스트(채팅 단축어 자동완성). 한 곳만 고치면 같은 모양의 목록에서 포커스 표시가 갈린다.
- **격자형 피커(아이콘·색, `shared/ui/color-icon-picker/`)의 옵션은 이 1px 링에 하우스 레시피의 바깥 `ring-3 ring-ring/50`을 더한다** — 옵션이 글 행이 아니라 그림 칸이라 1px만으로는 스와치 둘레에 붙어 스와치 테두리로 읽혔고, 바로 옆 트리거(1px + 3px)보다 확연히 얇았다. 선택은 `foreground` 2px 보더라 링과 다른 속성이어서 겹쳐도 둘 다 남고, 바깥 링은 칸 사이 간격(4px) 안에 든다.
- **`outline-hidden`을 쓴 리스트를 새로 만들면 링을 함께 넣는다.** 그 유틸리티가 UA 아웃라인을 지우므로, 넣지 않으면 남는 신호가 1.1:1짜리 배경 변화 하나뿐이다.
- **비활성 항목은 `opacity-65`다**(상류 shadcn은 `opacity-50`). 50%면 항목 글자가 팝오버 위에서 **3.2515 라이트 / 4.4959 다크**로 AA 아래고, 이 앱은 "왜 못 누르는지"를 읽혀야 하는 비활성 항목이 있다. 65%면 **5.1882 / 6.7086**이다. Radix가 비활성 항목을 키보드 이동에서 건너뛰고 `pointer-events: none`이라 링은 그려지지 않는다(실측).
- **목록이 잘렸다는 신호는 페이드뿐이다** — 아래에 더 있으면 바닥 32px, 위에 더 있으면 꼭대기 32px이 팝오버 색으로 흐려지고 그 끝에 닿으면 사라진다. 셀렉트는 위·아래 둘 다, 드롭다운은 아래만 쓴다(드롭다운은 위가 잘리는 게 사용자가 스크롤한 뒤뿐이지만 셀렉트는 선택 항목으로 스크롤된 채 열린다). 셀렉트의 스크롤바는 Radix가 모든 OS에서 숨기고 스크롤 화살표 버튼도 두지 않으므로 이 페이드 말고는 신호가 없다. 근거와 배선은 `packages/ui/src/components/select.tsx`의 `SelectContent` 주석에 있다.

### Navigation
- **상시 크롬은 위쪽 헤더 한 줄과, `lg` 이상의 좌측 패널 한 열이다.** 헤더는 `sticky top-0 z-30 border-b border-border bg-background`(`h-14`는 안쪽 바에 걸려 헤더 총높이는 border 포함 57px)이고 안쪽 바는 놓인 열을 꽉 채운다(`mx-auto max-w-*` 없음, `px-4 sm:px-6`만) — `lg` 미만에서는 뷰포트, `lg` 이상에서는 패널 오른쪽 열이다. 본문은 `max-w-5xl` 컬럼에 산다. 정렬 관계는 경계 양쪽에서 다르다: `lg` 미만은 로고가 헤더 가운데라 본문 left와 비교하지 않는다. `lg` 이상은 패널 안의 잉크(로고·내비 아이콘·최근 대화 썸네일)가 모두 x=24에서 시작하고, 헤더 첫 글자(유형 탭)는 패널 오른쪽 + 24에 앉으며(탭 패딩만큼 `-ml-2`로 당긴다), 본문 콘텐츠 left는 패널 오른쪽 + max(24, (남은 폭 − 1024)/2 + 24)다 — 남은 폭이 1024px 이하면(뷰포트로 펼침 1264px·레일 1088px 이하) 헤더 첫 글자와 본문 left가 같은 x이고, 그 이상에서는 본문이 가운데로 들어가며 벌어진다(실측, 헤더 첫 글자 x · 본문 콘텐츠 x: 1024px 펼침 264 · 264, 레일 88 · 88 / 1440px 펼침 264 · 352, 레일 88 · 264 — 첫 글자 x는 첫 탭 left + 탭 패딩 8px). 폭을 잴 때는 스크롤바를 중화한다 — 한때 "1440px 실측"이라 적힌 값이 실제로는 스크롤바만큼 줄어든 1425px 실측이었다. 하단 탭바·두 번째 가로 줄·오른쪽 레일·sticky/fixed 푸터는 **존재하지 않으며, 추가하지 않는다**. 문서 끝의 정보 푸터는 크롬이 아니다(아래 사이트 푸터 항목). 전역 크롬(헤더와 패널)을 그리지 않는 화면은 셋이고(빌더, 소설 화 읽기 — 내 소설과 노벨 두 경로, 소설 편집 보드 — 아래 각 항목), 판정은 헤더와 패널이 함께 쓰는 `widgets/header/lib/isGlobalHeaderHidden.ts` 한 곳에 있다 — 둘을 다른 함수로 가르면 헤더 없는 화면에 패널만 남는 화면이 생긴다.
- **이 금지의 대상은 전역 크롬이다 — `<main>` 안에서 한 라우트의 콘텐츠를 여러 열로 나누는 것은 대상이 아니다**(`BuilderLayout`의 lg 2단, `/studio/images`의 lg 3단, 작성 가이드 단계 페이지의 lg 설명 ↔ 칸 그림 2열). **금지의 본질은 크롬이 콘텐츠의 자리를 늘 차지하는 것이다 — 그래서 크롬의 자리는 둘로 닫혀 있다: 위쪽 헤더 한 줄, 그리고 `lg` 이상의 좌측 패널 한 열.** 판별은 두 단계다 — ① 모든 라우트에 상시 존재하는가(그렇다면 크롬이다) ② 크롬이라면 그 두 자리 안에 들어가는가. 크롬이 아니면(그 라우트에만 있거나, 부를 때만 오는 일시적 표면이면) 페이지 콘텐츠이고, 크롬인데 두 자리 밖이면(하단 탭바, 두 번째 가로 줄, 오른쪽 레일, 고정 푸터) 금지다. **①이 거짓이어도(그 라우트에만 있어도) 정지 상태에 sticky/fixed로 늘 자리를 차지하는 띠를 헤더 자리 밖에 더하면(그 화면만의 두 번째 가로 줄, 고정 하단 바) 금지다** — 헤더 자리를 대신하는 한 줄(빌더·소설 편집 보드의 전용 상단바, 소설 화 읽기 화면의 위 바)은 더한 것이 아니고, 기록된 예외는 상세화면의 하단 플레이 바 하나다. 소설 화 읽기 화면의 넘김 버튼은 판형 바깥 여백 안의 아이콘 둘이라 띠가 아니고, `<main>` 흐름 안에서 콘텐츠를 여러 열로 나누는 것도 띠가 아니다. 새 목적지는 두 자리 중 하나에 넣는다 — 자리를 새로 만들지 않는다.
  **좌측 패널을 자리로 연 이유**는 두 가지 사실이다. 첫째, 가로 띠는 모든 화면이 쓰는 세로 높이를 깎지만, 좌측 열은 넓은 화면에서 본문 컬럼(`max-w-5xl`)이 쓰지 않는 가로 여백을 쓴다 — 펼친 패널은 뷰포트 1264px 이상, 레일은 1088px 이상에서 본문 컬럼 폭을 1px도 줄이지 않는다. 그보다 좁은 `lg`~`xl`에서는 패널이 본문을 좁히므로 저장값이 없으면 레일로 시작하고, 폭을 가장 많이 쓰는 채팅·이미지 스튜디오는 바깥에서 들어올 때 늘 레일로 시작한다(아래 좌측 패널 항목). 둘째, 데스크톱에서 어제 대화로 돌아가는 길이 프로필 메뉴를 열고 내 채팅목록을 거쳐 방을 고르는 세 번이었다 — 패널의 최근 대화가 그것을 한 번으로 줄인다. `lg` 미만에는 첫째 사실이 성립하지 않아 패널이 없고(태블릿 세로 768px에 240px 패널을 두면 본문이 528px로 줄어든다), 같은 내용을 버거로 여는 드로어가 진다.
  **예외 목록이 아니라 자리를 다시 정의한 이유**: 예외가 셋이 되면 원칙보다 예외 목록이 규칙이 된다(이 조항의 첫 번째 개정은 이미지 페이지 3열, 두 번째는 "역할이 화면 전환인가"를 단독 기준에서 내린 것이다). **기존 선례는 새 판별로도 같은 결론이다**: `/studio/images`의 좌열(보관함)·우열, 소설 편집 보드의 옆 패널, 채팅 더보기 패널은 그 라우트에만 있어(①거짓) 페이지 콘텐츠다. 버거로 여는 좌측 드로어와 소설 화 읽기 화면의 위·아래 바는 부를 때만 오는 일시적 표면이라 상시가 아니다(①거짓). 넘김 버튼은 그 라우트에만 있고(①거짓) 띠가 아니다. 정보 푸터는 거의 모든 문서 화면에 있지만 내비게이션이 아니라 정보이고 문서 흐름의 끝에 놓여 콘텐츠 자리를 늘 차지하지 않는다 — 이 시험의 대상이 아니다. 상세화면 하단 플레이 바는 그 화면 하나의 단일 전환 액션이고(①거짓, Overview 절), 정지 상태의 고정 하단 바라 위 띠 문장의 기록된 예외다. **이 판별을 근거로 세 번째 크롬 자리(오른쪽 레일, 하단 바, 두 번째 가로 줄)를 만들지 말 것** — 자리는 둘로 닫혀 있다.
- **좌측 패널**(`widgets/header`, `lg` 이상에서만 마운트)은 `sticky top-0 h-dvh`이고 `border-r border-border bg-background`다 — 헤더와 같은 면·같은 경계 레시피이고, 정지 상태 그림자가 없다. 머리는 헤더와 같은 구조(바깥 `border-b` + 안쪽 `h-14`, 총 57px)라 패널 머리 선과 헤더 선이 y=56에서 한 줄로 이어진다 — `h-14`와 `border-b`를 한 요소에 걸면 border-box라 56px가 되어 1px 어긋난다(실측: 패널 머리 하단·헤더 하단 모두 57, 선은 y=56~57 — `lg` 이상 6폭 × 펼침·레일 전부).
  - **두 상태**: 펼침 240px(`w-60`)와 아이콘 레일 64px(`w-16`)를 머리의 토글로 오간다. 펼침 머리는 워드마크 로고(왼쪽)와 접기 버튼(오른쪽), 레일 머리는 심볼만이고 펼치기 버튼은 머리 바로 아래 첫 칸이다(64px에 심볼과 버튼을 나란히 두면 좌우 여백이 약 4px뿐이다). 두 상태 모두 Tab 순서는 로고 → 토글 → 내비다. 토글의 접근 이름은 할 동작("사이드바 접기"/"사이드바 펼치기")이다.
  - **접힘 상태 규칙**: 저장값은 사용자가 토글로 바꿀 때만 생기고(이 브라우저의 편의 설정이라 `localStorage`, 읽기·쓰기가 실패하면 저장값 없음으로 동작), 있으면 `lg` 이상 모든 폭에서 이긴다. 채팅(`/chat/$roomId`)·이미지 스튜디오(`/studio/images`)는 바깥에서 들어올 때 늘 레일로 시작하고, 거기서 펼친 것은 저장하지 않는다 — 채팅에서 다른 채팅으로 옮길 때(패널의 최근 대화로)는 그 화면의 상태를 지킨다. 저장값이 없으면 `xl`(1280px) 이상 펼침, `lg`~`xl` 레일이고 창 크기를 따라간다.
  - **항목**: 내비(홈 · 작품 만들기 · 내 작품 · 내 소설(허용된 계정만) · 이미지 생성 · 즐겨찾기)와 최근 대화 10개 + "전체 보기"(`/chats`). 레일에는 내비 아이콘과, 1px 선 아래 내 채팅목록 아이콘 하나(`/chats`)만 있고 최근 대화는 없다. 목적지 목록은 프로필 메뉴·드로어와 같은 한 소스에서 패널 몫과 메뉴 몫을 겹치지 않게 나눈다. 패널 하단에는 아무것도 두지 않는다 — 프로필·클로버·알림은 헤더에 있다.
  - **행**: 높이 36px(손가락 포인터 40px), 아이콘 16px, 정지 라벨 `muted-foreground`, hover·현재 채움 `secondary`에 글자 `foreground`(라이트 `muted-foreground` on `secondary`는 4.30:1, Colors 절). **현재 항목**(`aria-current="page"`)은 채움·`font-semibold`에 더해 왼쪽 1px `foreground` 막대(행 위아래 8px 띄움)를 둔다 — 채움만으로는 3:1에 못 닿고(Colors 절 "정보를 싣는 선택 상태"), 굵기는 라벨이 숨는 레일에서 사라지며, 글자색 변화는 다크에서 2.34:1이라 레일과 펼침 모두에서 3:1 이상으로 남는 단서가 따로 있어야 한다. 막대 대 `secondary` 채움은 다크 12.64 / 라이트 14.09:1(계산값 — 픽셀 실측 다크 12.67 / 라이트 14.06:1, 패널 펼침·레일·드로어 모두 같다)이고, 1px라 Do's and Don'ts의 사이드 보더 금지와 Chat Notation 절이 사용자 메시지 선을 1px로 둔 이유 안에 든다. 레일에서는 hover(같은 채움 + `foreground` 아이콘)와 이 막대 하나로 갈린다. 그 단서는 `primary`가 아니다. 포커스는 50% 링 + 불투명 1px 아웃라인이고, 패널 안 스크롤 영역은 링 두께 이상의 안쪽 여백(8px, 레일 12px)을 둬 첫·끝 행의 링이 잘리지 않는다. 패널 안 잉크(로고·아이콘·썸네일·섹션 라벨)는 x=24에서 시작하고, 레일 아이콘 중심도 펼침과 같은 x=32라 접고 펼 때 아이콘이 가로로 움직이지 않는다.
  - **최근 대화 행**: 썸네일 32px(사용자 콘텐츠 — 패널 안에서 색을 가진 유일한 것) · 작품명 한 줄 · "방 이름 · 상대 시각" 한 줄. 같은 작품의 방은 썸네일·작품명이 같고 방 이름과 시각이 가른다. 미리보기 문장과 행 메뉴는 두지 않는다. 로딩은 행 모양 스켈레톤, 0개는 문장 하나, 불러오기 실패는 문장 + "다시 시도", 비로그인은 안내 문장 + "로그인하고 보기"(`outline` — 비로그인 헤더의 "로그인"이 그 화면의 솔리드다). 썸네일 웰은 패널에서 `muted`, 드로어(`popover`)에서 `secondary`이고, 둘 다 `foreground/10` 테두리를 둬 hover 채움과 웰이 같은 값이 되는 드로어에서도 경계가 남는다.
  - **레일 툴팁**은 공용 `Tooltip`(Radix)이고 오른쪽에 뜬다. 표면은 반전 말풍선이 아니라 Elevation 절의 Floating panel(`popover` + `shadow-md` + `ring-1 ring-foreground/10`)이다 — 다크에서 0.930 말풍선이 갑자기 켜지는 것은 예고 없는 대비 점프다. 키보드 포커스에도 뜬다.
  - **모션**은 Motion 절의 좌측 패널 폭 항목을 따른다.
  - **분기**: 패널은 JS(`(min-width: 64rem)` — CSS `lg:`와 같은 문자열)로 `lg` 이상에서만 마운트한다 — CSS로 숨기면 `lg` 미만에서도 보이지 않는 최근 대화 조회가 화면마다 돈다. 헤더 안의 로고·버거·탭은 한 DOM에 CSS로 가른다(아래).
  - **스킵 링크**: 전역 크롬이 있는 화면의 첫 Tab 정지는 "본문으로 건너뛰기"다(포커스 때만 왼쪽 위에 나타남, 대상은 셸의 본문 래퍼) — 패널이 본문 앞 Tab 정지를 24개로 늘리기 때문이다(실측: 펼침, 로그인·최근 대화 10개, 내 소설 권한과 노벨 링크가 없는 계정 — 둘이 있으면 26개, 레일은 14 / 16개).
- **예외는 빌더 라우트다** — `/builder`(타입 선택)·`/builder/$type/$draftId` 둘 다 전역 헤더를 렌더하지 않는다(`routes/__root.tsx`가 `isGlobalHeaderHidden(pathname)`이 참이면 `<Header/>`를 건너뛴다). 대신 같은 56px 자리에 전용 상단바(`features/build-common`의 `BuilderTopBar`)가 들어가므로 **크롬은 여전히 한 줄**이고, 아래 `calc(100dvh-3.5rem)`류 높이 계산도 그대로 유지된다(크랙 실측 상단바가 마침 56px로 같았던 것을 활용했다). 좌측 패널도 그리지 않는다 — 빌더 폼 열 672px·보드 캔버스 폭 같은 아래 Layout containers 절 실측이 "뷰포트 = 본문 폭"을 전제하기 때문이다. 상단바는 뒤로가기(항상 `/my`)·제목(h1)·액션(작성 가이드 새 탭 링크/미리보기 — 미디어 북 탭에서는 배치표/임시저장/발행)·자동저장 안내문 넷을 한 행에 담는다(폭이 모자라면 제목이 말줄임으로 줄어 액션이 바 밖으로 넘치지 않는다) — 타입 선택 화면은 폼이 없어 액션·안내문 없이 뒤로가기·제목만 쓴다. `sm`(640px) 미만에서는 이 절의 라벨 숨김 선례(`hidden sm:inline`)를 그대로 따라 액션 버튼이 아이콘만 남는다(`aria-label`은 유지) — 실측으로 390·360·320px에서 라벨이 숨고 640px에서 보인다.
- **소설 편집 보드(`/novels/$novelId/board`)도 빌더와 같은 꼴의 예외다** — 전역 헤더 대신 같은 56px 자리에 전용 상단바(`widgets/novel-board`의 `NovelBoardTopBar`, 클래스는 `BuilderTopBar`와 같다)를 두므로 크롬은 여전히 한 줄이고, 그 아래는 `h-below-header` 뷰포트 고정 화면이라 사이트 푸터가 없다. 좌측 패널도 그리지 않는다 — 빌더 폼 열 672px·보드 캔버스 폭 같은 아래 Layout containers 절 실측이 "뷰포트 = 본문 폭"을 전제하기 때문이다. 상단바는 작품 정보로 가는 뒤로가기(고정 목적지)·소설 제목(h1)·배치 자동 저장 안내문·버전·다음 화 만들기(그 화면의 유일한 솔리드)를 한 행에 담고, `sm` 미만에서는 빌더처럼 액션 라벨이 숨는다. `lg`(1024px) 이상에서 본문은 캔버스와 오른쪽 옆 패널(`border-l`, 폭 `w-md` · `xl` 이상 `w-lg`) 두 열이다 — 옆 패널은 그 라우트에만 있어(위 판별 ①거짓) 크롬이 아니라 `BuilderLayout` 2단과 같은 `<main>` 옆 열이다. `lg` 미만에서는 캔버스를 그리지 않고 같은 데이터를 세로 흐름 목록(화·인물·설정 탭)으로 보이며, 카드를 고르면 목록 자리에 같은 패널 내용이 온다 — **시트가 아니라 화면 전환이다**: 목록 화면이 고른 것의 편집 화면으로 바뀌고, 맨 위 `← 목록`이나 기기의 뒤로 가기로 목록에 돌아간다(고른 것이 주소에 남아 기록에 쌓이기 때문이다). 시트로 띄우지 않는 이유는 시트에서 실제로 달라지는 것들이다 — 시트(`popover` 표면) 위에서는 재사용하는 문단 버튼의 `hover:bg-muted`가 표면과 같은 값이라 사라지고, 긴 본문 편집이 시트 안 스크롤이 되며, 수정·판 이력 모달이 포커스를 가둔 시트 위로 겹친다. 캔버스와 목록, 옆 열과 그 대체는 둘 중 하나만 마운트되므로 JS로 가른다(Layout containers 절). 이 예외는 그 라우트에만 걸리고, 다른 화면에 전용 상단바나 옆 패널을 둘 근거가 되지 않는다.
- **또 하나의 예외는 소설 화 읽기 화면(몰입 뷰어, 내 소설 `/novels/$novelId/episodes/$chapterId`와 노벨 `/webnovels/$novelId/episodes/$chapterId`)이다** — 전역 헤더도 좌측 패널도 사이트 푸터도 그리지 않는다. 오래 읽는 화면이라 정지 상태에는 본문만 빛난다(예외 하나는 아래 넘김 버튼). 넘김 방식은 보기 설정에서 고르고 기본은 페이지 모드다. 넘김 방식을 바꿔도 읽던 문단에서 이어진다.
  **페이지 모드는 고정 판형이다.** 한 쪽은 논리 크기 360×540px(2:3)의 판형 한 장이고, 화 본문을 그 판형에 조판한 뒤 판형 전체를 화면에 맞춰 키우고 줄인다(`transform: scale` — `zoom` 은 배율마다 다시 조판해 쪽 수가 바뀐다). 그래서 같은 글자 크기·줄 간격 설정이면 기기·창 크기·포인터와 무관하게 한 화가 같은 쪽 수다(같은 렌더 엔진 안에서 — 엔진마다 줄 나눔이 달라 ±1쪽 차이가 날 수 있다). 판형 안의 글자·간격은 전부 px 로 고정한다 — rem 이면 브라우저 기본 글자 크기 설정이 쪽 수를 바꾼다(Typography 절의 히어로 없음 규칙 예외). 문단 간격은 글자 크기와 같다. 판형 안쪽 여백은 사방 24px 이고, 펼친 두 쪽 사이 글 간격은 48px, 가운데 선은 없다. 배율은 0.8~1.2 로 묶고, 상한에 걸리면 판형 둘레가 빈다. 펼쳐도 배율이 줄지 않을 때만 판형 두 장을 펼친다. 배율이 하한 밑인 화면(가로로 눕힌 폰, 아주 낮은 창)에서는 그 기기에서만 스크롤 모드로 보이고 토스트 한 줄("화면이 작아 이 기기에서는 스크롤로 보여요. 화면이 넉넉해지면 페이지로 돌아가요.")로 알린다 — 저장된 넘김 방식은 바꾸지 않고, 보기 설정의 넘김 방식 줄 밑에 "지금 화면에서는 스크롤로 보여요"를 단다. 판정은 기기 종류가 아니라 배율 하나다. 하한 밑에서 페이지 모드로 돌아올 때는 배율이 0.81 이상이어야 한다 — 창을 끌어 크기를 바꾸는 중처럼 배율이 하한 근처에서 오갈 때 모드가 그때마다 바뀌지 않게, 0.80~0.81 사이에서는 지금 모드를 지킨다(띠가 판형 높이로 5px 남짓이라 모바일 주소창이 접히고 펴지는 차이로 오가는 것까지는 막지 못한다).
  **쪽은 논리 쪽(판형 한 장)이다** — 펼침이면 한 화면에 두 쪽("3–4 / 16쪽")이고, 화 끝 쪽도 한 쪽으로 센다. 쪽 수는 본문 글꼴(Pretendard)이 도착한 뒤에만 보인다 — 대체 글꼴로 잰 쪽 수는 다를 수 있다. 그 전에도 본문은 대체 글꼴로 바로 그려지고 넘길 수 있다. 첫 쪽 위에는 작품 정보로 가는 링크와 화 제목(h1)이 있고, 본문이 끝나면 작가의 말·다음 화·목차·작품 정보만 담은 화 끝 쪽이 따로 한 쪽을 차지한다(펼침이면 새 펼침의 왼쪽 쪽, 세로 가운데). 첫 쪽에서 이전으로, 화 끝 쪽에서 다음으로 넘기면 멈춘다 — 다른 화로는 버튼으로만 간다. 넘기는 길은 넘김 버튼, 본문 탭(창 폭의 왼쪽 25% = 이전, 오른쪽 25% = 다음, 가운데 50% = 바 여닫기 — 영역은 그리지 않는다), 가로 스와이프·마우스 끌기, 휠 한 번(트랙패드 한 번 밀기)에 한 화면, 키보드(`←`/`→`·`PageUp`/`PageDown`·`Space`/`Shift+Space`, `Home`/`End`)다. 마우스 끌기·터치 넘김이 텍스트 선택과 같은 손짓이라 **페이지 모드에서는 본문을 선택할 수 없다** — 복사는 스크롤 모드에서 한다. 트랙패드 가로 밀기가 브라우저의 뒤로 가기 손짓으로 새지 않게, 페이지 모드 동안은 문서 루트의 가로 오버스크롤(`overscroll-behavior-x`)을 끈다.
  **위·아래 바 자리는 페이지 모드에서 늘 비어 있다** — 판형은 위 바 자리(57px + 상단 safe-area)와 아래 바 자리(57px + 하단 safe-area) 사이에 놓이므로, 바가 나타나도 글을 가리지 않고 바를 여닫아도 판형·글자·쪽 경계가 1px 도 움직이지 않는다. 바 한 줄 높이(56px)는 판형 배율 계산과 바 컴포넌트가 같은 상수 하나를 쓴다. **스크롤 모드**는 문서 스크롤이라 바가 본문 위에 겹쳐 나타나고, 본문 아무 곳이나 탭하면(10px 미만·300ms 미만·선택 없음·링크나 버튼 밖) 바를 여닫는다.
  **넘김 버튼은 정지 상태에 보이는 유일한 조작이다.** 네 조건이 모두 참일 때만 그린다 — 이 라우트, 페이지 모드, 마우스·트랙패드 기기(`(hover: hover) and (pointer: fine)`), 판형 바깥의 좌우 여백. 배율을 계산할 때 버튼 자리(한쪽 56px)를 가용 폭에서 먼저 빼므로 어떤 창 폭에서도 판형을 가리지 않고, 판형 크기에는 영향이 없어 포인터 종류가 쪽 수를 바꾸지 않는다. 판형 바깥 8px, 판형 세로 가운데, 40px 누르는 면에 아이콘만 두고, 정지 색은 `input`이다 — 컨트롤로 알아볼 하한(배경 대비 3:1)은 넘지만 본문 `foreground`보다 훨씬 어두워 읽는 동안 눈에 걸리지 않는다. hover 는 ghost 버튼 그대로 `muted` 채움에 `foreground`, 키보드 포커스 때도 아이콘이 `foreground`로 밝아지고, 첫 쪽의 이전·화 끝 쪽의 다음은 `aria-disabled`(포커스는 남는다). 터치 기기에는 넘김 버튼이 없다 — 손가락은 탭 영역·스와이프·아래 바의 쪽 슬라이더로 넘긴다.
  화를 열 때(이전·다음 화로 옮긴 뒤에도) 바는 숨은 채로 시작한다. 바를 부르면 위 바(56px 한 줄, 상단 safe-area 포함 — 뒤로 · 화 제목과 그 밑 화 안 위치 · (노벨 경로만) 댓글 · 목차 · 보기 설정)와 아래 바가 나타나고, 다시 탭하거나 `Esc`를 누르면 숨는다. 두 바 모두 좌우 safe-area 를 더해, 가로로 눕힌 노치 폰에서도 양끝 버튼이 노치·둥근 모서리 밑에 깔리지 않는다. 화 안 위치는 위 바 제목 밑 한 줄이다 — 페이지 모드 "3/12화 · 3–4 / 16쪽", 스크롤 모드 "3/12화 · 40%". 페이지 모드의 아래 바는 한 줄(56px + 하단 safe-area)이고 이전 화 · 쪽 이동 슬라이더(한 칸이 한 화면, 펼침이면 펼침 하나) · 다음 화를 담는다 — 이전·다음 화는 좁은 화면에서도 글자를 남긴다(아이콘만이면 쪽 넘김으로 읽힌다). 스크롤 모드의 아래 바는 위 가장자리의 얇은 진행 막대와 이전·다음 화 한 줄이다. 슬라이더는 공용 `Slider` 이고 채운 구간과 썸 윤곽을 호출부에서 `primary` 대신 `foreground` 로 덮는다 — 이 화면의 솔리드 채움은 화 끝 "다음 화" 하나여야 해서다(포커스 윤곽은 `ring` 그대로). 쪽 수를 재기 전에는 슬라이더 자리에 썸 없는 트랙만 있어 바 높이가 바뀌지 않는다.
  보기 설정은 아래 바 위에 뜨는 비모달 패널이라 본문을 흐리지 않고 판형도 움직이지 않는다 — 설정을 바꾸면 패널 뒤에서 쪽이 다시 나뉘고 읽던 문단이 시작하는 쪽으로 가므로, 패널 위로 보이는 판형 윗부분에서 결과를 바로 본다. 패널의 줄은 어느 폭에서나 라벨과 칩을 한 행에 놓고(덮는 높이를 줄이려고), `sm` 이상에서는 줄을 두 열로 놓는다. 숨은 바는 `inert`라 포커스와 보조기기 모두에서 빠지고, 대신 문서 첫 Tab 정지에 늘 닿는 "메뉴 열기" 버튼(평소 시각적으로 숨김, 포커스 때 보임)이 바를 연다. 노벨 경로의 화 댓글은 판형 흐름 밖의 시트(`md` 미만 아래 시트, 이상 오른쪽 시트)로 열린다 — 쪽 수가 댓글 수에 기대지 않게 하려는 것이다. 여는 곳은 위 바의 댓글 버튼과 화 끝의 "댓글 n" 둘이고, 화 끝에는 그 옆에 소설 좋아요가, 맨 아래에 작은 "이 화 신고하기"가 함께 놓인다(그 화면의 솔리드는 여전히 "다음 화" 하나다). 바의 등장·퇴장과 쪽 넘김의 움직임은 Motion 절을 따른다. 바에는 그림자가 없고 `border`로만 본문과 갈린다. 위 판별로 보면 이 바들과 넘김 버튼은 크롬이 아니다 — 그 라우트에만 있고, 바는 부를 때만 오는 일시적 표면이다(좌측 드로어와 같은 논리). 페이지 모드에서 바 자리를 늘 비워 두는 것도 크롬을 더하는 것이 아니다 — 비어 있는 자리이지 정지 상태에 그려지는 줄이 아니다. **이 예외는 화 읽기 라우트에만 걸리고 다른 화면으로 번지지 않는다** — 작품 정보(`/novels/$novelId`·`/webnovels/$novelId`)와 소설 목록(`/novels`·`/webnovels`)은 전역 헤더와 사이트 푸터를 그대로 쓰는 평범한 문서 화면이며, 이 항목을 다른 화면에 하단 바·탭으로 숨는 헤더·상시 넘김 버튼·고정 판형을 둘 근거로 쓰지 말 것.
- **사이트 푸터는 하나뿐이고 문서 끝에만 있다.** `routes/__root.tsx`가 오른쪽 열의 아웃렛 뒤에 `<footer>` 하나를 마운트한다 — 루트가 가로 flex(좌측 패널 | 오른쪽 열)이고 오른쪽 열이 `flex-col`, 페이지 영역이 `flex-1`이라 짧은 페이지에서는 뷰포트 바닥에, 긴 페이지에서는 끝까지 스크롤해야 만난다. `lg` 이상에서 푸터는 오른쪽 열 폭이다(패널 아래로 뻗지 않는다). sticky/fixed로 만들지 않는다. **뷰포트 고정 화면과 빌더 라우트, 소설 화 읽기 화면에는 렌더하지 않는다** — `/chat/*`·`/builder/*`·`/studio/images`·`/novels/$novelId/board`(`h-below-header`를 쓰는 뷰포트 고정 화면들)와, 빌더 셸의 입구라 전역 헤더도 건너뛰는 `/builder`(타입 선택), 그리고 두 화 읽기 경로(`/novels/$novelId/episodes/$chapterId`·`/webnovels/$novelId/episodes/$chapterId`). 화 읽기 화면은 전역 크롬을 모두 걷은 몰입 뷰어라 넘김 방식과 무관하게 사이트 정보를 붙이지 않는다 — 페이지 모드는 뷰포트 고정이라 붙일 문서 끝이 없고, 문서 스크롤인 스크롤 모드도 본문이 끝난 자리에는 다음 화로 가는 버튼이 온다. 같은 소설의 작품 정보 화면과 노벨 목록은 푸터를 유지한다. 숨길 라우트 판정은 순수 함수 하나에 모은다(빌더의 헤더 건너뛰기 규칙은 그대로 둔다). 비주얼: 기본 배경 위 `border-t border-border`(카드 표면·그림자 없음), 안쪽 컨테이너 `mx-auto max-w-5xl px-4 sm:px-6`, 링크는 `text-xs` `text-muted-foreground` + `hover:text-foreground`, 아래 패딩은 safe-area를 포함한다. 링크 목록 아래에는 운영자 정보 블록이 있다 — 상호·대표자·사업자등록번호·통신판매업·주소·전화·이메일·호스팅 제공자를 항목 이름과 값으로 나눈 `<dl>`이고, 이름과 값 모두 링크와 같은 `text-xs text-muted-foreground`에 `break-keep`이다(값에 `whitespace-nowrap`을 걸지 않아 390px에서도 가로 스크롤이 없다). 이름을 굵게 하거나 밝히지 않는다 — 아래 강조 규칙이 그대로 하나로 남아야 해서다. 공정거래위원회 사업자정보 확인 링크는 통신판매업 신고번호가 있을 때만 나온다. 값의 원본은 web `shared/config`의 사업자 정보 상수다. 콘텐츠 상세화면의 `lg` 미만에서는 하단 고정 플레이 바 위로 올라오는 아래 패딩을 푸터가 진다(그 화면의 `<main>`은 더 이상 지지 않는다). **강조는 `개인정보처리방침` 링크 하나뿐이다** — 처리방침은 로그인 없이 첫 화면에서 찾을 수 있고 다른 링크와 시각적으로 구별돼야 한다는 개인정보 처리방침 작성 지침 때문이다. 강조는 `font-semibold` + `text-foreground`이지 `primary`가 아니다 — `primary`는 유일한 강조색으로 남는다. **푸터에 `/my`(내 작품) 링크를 두지 않는다** — 이름이 `내 작품`인 링크는 접근성 트리에 많아야 하나다(`lg` 이상은 좌측 패널의 내비 항목, `lg` 미만은 드로어가 닫혀 있으면 0개). `/mypage` 본문의 `/my` 링크는 라벨("만든 작품과 초안 보기")로 갈린다(`MyPagePage.tsx` 주석).
- **web과 admin은 같은 꼴(좌측 열 + 상단바)을 다른 이유와 다른 면으로 쓴다**(admin은 `widgets/admin-shell`). admin은 화면 전환 자체가 주 동작인 운영 콘솔이라 모든 화면이 목록·상세 사이 이동이고, 북극성이 적용되지 않아(라이트 고정, Overview 절) 사이드바를 `card` 면에 두고 현재 항목에 `primary` 막대를 쓴다. web의 좌측 패널은 위 판별 항목의 두 사실(넓은 화면의 남는 가로 여백, 최근 대화로의 한 번 복귀) 위에 서고, 북극성 아래에 있어 면이 `background`(헤더와 같은 레시피 — 정지 상태에 밝기 예산을 쓰지 않는다)이고 현재 항목 표시가 무채색이다(1px `foreground` 막대, 위 좌측 패널 항목). **펼침 폭이 admin 224px와 다른 240px인 이유**: web 패널은 최근 대화 행(썸네일 32px + 작품명·방 이름 두 줄)을 담는데, 240px에서 글자 열이 147px, 224px에서 131px라 작품명이 16px 한글로 한 자 더 들어간다. 두 폭 모두 `xl`(1280px)에서 본문 컬럼을 줄이지 않는다(1280 − 240 = 1040 ≥ 1024) — 그 점은 둘을 가르지 않는다.
  - **`lg`(1024px) 이상은 사이드바, 미만은 상단바 + 드로어다**(둘은 CSS로만 갈린다). 사이드바는 펼침 224px(`w-56`)과 아이콘 레일 64px(`w-16`) 두 상태를 머리의 토글로 오간다. 접힘 여부는 이 브라우저의 편의 설정이라 `localStorage`에 두고, 읽기·쓰기가 실패하면 펼침으로 시작한다. 레일에서도 각 항목의 접근 이름은 화면명이다 — 라벨을 화면에서만 숨기고(`sr-only`) 그룹 사이는 1px 선으로 나눈다. 사이드바는 `sticky top-0 h-dvh`이고 내비 목록만 스크롤해, 낮은 화면에서도 아래 계정·로그아웃이 밀려나지 않는다. `lg` 미만에서는 사이드바를 그리지 않고 `h-14` sticky 상단바 한 줄(버거 · "또나 어드민" · 현재 화면명 · 빠른 이동 버튼)과 좌측 드로어(`Sheet side="left"`)로 바꾼다 — 태블릿 세로(768px)에 사이드바를 두면 본문이 544px만 남는다. 드로어의 링크 목록은 사이드바와 같은 컴포넌트라 마크업이 한 벌이다. 링크를 누르면 드로어가 닫히고 포커스는 새 화면 본문으로, Esc로 닫으면 버거로 돌아간다.
  - **내비는 네 그룹이다** — 개요(대시보드·사용량 모니터링) / 검토 큐(신고·이의제기·문의) / 콘텐츠·유저(작품·유저·이미지 생성) / 서비스 설정(공지·약관·프롬프트). 행은 테두리 없는 ghost 행이고 hover·활성 채움은 `secondary`다(사이드바는 `card`, 드로어는 `popover` 위라 `muted` 채움은 보이지 않는다). 활성은 거기에 `font-semibold`와 왼쪽 `primary` 막대 하나를 더한다 — `primary` 틴트 채움이나 테두리를 함께 쓰지 않는다. 대기 건수 배지는 없다. 상세에서도 부모 항목이 활성이고, 이미지 생성 목록에서 들어간 유저별 생성 이미지 화면은 유저가 아니라 이미지 생성 항목이 활성이다(그 진입을 URL search가 기억한다).
  - **빠른 이동 팔레트를 여는 자리는 늘 보인다** — 사이드바 머리 아래 "빠른 이동" 버튼(레일에서는 아이콘 버튼), 상단바의 돋보기 버튼. 단축키(맥 ⌘K, 그 밖 컨트롤+K)를 모르는 사람도 찾을 수 있어야 해서다. 팔레트는 공용 `Dialog` 안의 목록이라 새 표면을 더하지 않는다.
  - **하단 고정 조치 바는 admin 상세 화면에만 있는 예외다**(신고 상세 셋·유저 상세·작품 상세 — 걸 수 있는 조치가 있을 때만). `lg` 미만에서 그 화면의 조치를 여는 버튼 하나와 한 줄 요약을 하단에 고정하고, 누르면 바텀시트로 조치 패널이 올라온다. `lg` 이상에서는 같은 패널이 본문 오른쪽 sticky 열(18rem)에 있다. 패널은 한 번만 마운트되어 시트를 닫았다 열어도 입력이 남고, 조치가 성공하면 시트가 닫히고 포커스는 바 버튼으로 돌아온다. 위 web의 "상세 하단 플레이 바" 예외와는 별개다 — 그쪽은 화면을 바꾸는 단일 전환 액션이고 이쪽은 운영자가 그 대상에 거는 처리다. admin 안에서도 목록·대시보드·편집 화면(문의 답변·공지·약관·프롬프트 — 폼 자체가 본문이다)과 조치 없는 열람 화면으로 번지지 않는다. 바 높이는 safe-area를 더한 값이고, 본문 끝에 같은 높이의 여백을 둬 마지막 요소를 가리지 않으며 바가 있는 동안 토스트도 그만큼 올린다.
  - **폭과 터치.** 목록·대시보드·단일 화면은 `max-w-6xl` 컨테이너 하나, 상세는 본문 열과 조치 열이다 — 조치 열이 있으면 본문 열이 남는 폭을 다 받고(컨테이너 상한 안이라 최대 792px), 조치 열이 없는 상세(글·폼이 본문)는 `max-w-3xl`로 줄 길이를 묶는다. 거터는 web과 같은 `px-4 sm:px-6`. 사이드바가 접히고 펴지면서 본문 폭이 바뀌므로 본문 안 그리드는 뷰포트 브레이크포인트가 아니라 컨테이너 쿼리로 가른다. 손가락 포인터(`pointer: coarse`)에서는 버튼·셀렉트·토글·입력·가로 탭의 최소 높이를 40px로 올린다 — admin에만 로드되는 CSS가 프리미티브의 `data-slot`으로 건다(프리미티브를 고치면 web 화면 크기까지 바뀌어서다). 프리미티브가 아닌 손수 만든 행(내비 행·팔레트 항목)은 그 클래스에 직접 둔다. 글자 크기 그대로인 링크·표 칸 버튼은 박스 대신 투명한 의사 요소로 누르는 면만 넓힌다(늘 24px, 손가락 포인터 40px) — 문단 줄 간격은 바뀌지 않고, 손가락 포인터에서는 그런 대상을 담은 표 칸만 40px 높이가 돼 면이 이웃 행과 겹치지 않는다.
- **로고는 ㄸ 말풍선 심볼 + `또나` 글자를 한 장에 담은 SVG 워드마크다**(`widgets/header/ui/BrandLogo.tsx`, 높이 `h-5`, `text-foreground`). 로고는 `lg` 이상에서는 패널 머리(펼침은 워드마크, 레일은 같은 SVG의 심볼 부분만 — viewBox를 심볼 범위로 자른 변형), `lg` 미만에서는 헤더 가운데에 있다. **화면에 로고 홈 링크는 하나다**: 패널은 `lg` 이상에서만 마운트되고 헤더 로고는 `lg:hidden`(`display:none`이라 접근성 트리에서도 빠진다)이다. 패널 내비의 "홈" 항목은 로고와 라벨이 달라(`또나` / `홈`) 따로 둔다 — 로고를 눌러 홈에 가는 관습과, 레일에서 아이콘으로 홈을 찾는 길을 함께 지킨다. 글자는 Pretendard Bold 윤곽을 path로 굳힌 것이고, 높이는 ㄸ 윗변부터 말풍선 꼬리 끝까지에 맞춰 심볼과 위아래가 수평이다. 심볼은 ㄸ 전체가 말풍선 하나이고 첫 ㄷ 아래에서 꼬리가 왼쪽 아래로 내려온다 — 파비콘(`apps/web/brand/favicon.svg`)과 같은 도형이라 둘은 함께 바뀐다. 로고에 심볼을 붙인 이유는 파비콘이 글자 `또`에서 이 심볼로 바뀌어, 글자만 두면 탭의 마크와 화면의 마크가 서로 다른 브랜드로 보이기 때문이다. **색은 없다**: 심볼도 `currentColor`로 글자색을 따른다 — 로고는 강조 지점이 아니므로 `primary`가 아니라 `foreground`다(Colors 절의 One-Accent Rule). 브랜드 핑크는 파비콘의 어두운 타일 위에만 있다. 워드마크 SVG는 `aria-hidden`이고 홈 링크의 접근 가능한 이름은 링크의 `aria-label="또나"`가 진다.
- **모바일 대응은 라벨 숨김과 레이아웃 분기 둘 다 쓴다**(2026-09-14 개정 — 한때 "레이아웃 분기가 아니라 라벨 숨김이다"라고 적혀 있었으나 헤더 자체가 뷰포트별로 갈리는 지금은 거짓이다). 라벨 숨김은 빌더 상단바의 액션 버튼에 남는다(`hidden sm:inline`). **헤더는 경계 `lg`(1024px)에서 두 구성으로 갈린다** — `lg` 이상은 좌측 패널이 함께 있는 구성이다:
  - **`lg` 미만**: [버거 왼쪽] · [워드마크 중앙] · [검색 오른쪽] 셋뿐이다. 콘텐츠 유형 토글(옆의 "노벨" 링크 포함)·클로버·알림·프로필(비로그인은 로그인)은 좌측 드로어로 들어간다(아래). 640~1023px 태블릿도 이 구성이다.
  - **`lg` 이상**(패널 오른쪽): 텍스트 탭(캐릭터 · 스토리 + "노벨" 링크 — 노벨이 열려 있을 때만, 로그인과 무관하게) · `ml-auto` 아이콘 그룹(로그인 시 클로버 · 검색 · 알림 · 프로필, 비로그인은 검색 · 로그인). 로고는 패널 머리에 있다. 크롬에서 이미지 화면으로 가는 진입점은 패널의 "이미지 생성" 하나다.

  **구현은 한 DOM에 `grid grid-cols-[1fr_auto_1fr] … lg:flex`를 쓴다** — 마크업을 두 벌 두지 않는다(로고가 둘이면 접근가능한 홈 링크가 둘이고, 검색을 두 벌 마운트하면 상태가 갈린다). `display:none` 자식은 grid 아이템을 만들지 않으므로 `lg` 미만에서 버거=1열·로고=2열·우측=3열이 되고, `1fr auto 1fr`이라 버거와 검색의 폭이 달라도 로고가 정확히 중앙이다. `lg:flex`에서는 `grid-template-columns`가 무효라 되돌리는 클래스가 필요 없다.

  **헤더의 캐릭터/스토리 토글은 여전히 라벨 숨김의 대상에서 빠진다**(2026-09-14) — 아이콘이 없고 라벨을 항상 보이는 텍스트 탭이다. 토글 그룹 폭은 108.00 → **126.97px**(구현된 `px-2` 기준)로 커진다. **근거는 320px 넘침 방지가 아니다** — 그 압박은 토글이 `lg` 미만 헤더에서 아예 빠지면서 해소됐다(그 넘침 실측 자체는 버리지 않는다 — "토글이 모바일 헤더에 있던 동안의 값"으로 아래 §Toggles가 남긴다). `px-2`는 **텍스트 탭이 채움이 없어 알약 패딩이 필요하지 않기 때문**이다 — 패딩은 모양이 아니라 히트 영역만 정하고, `h-9`(36px)가 유지되므로 WCAG 2.5.8(24×24)을 그대로 만족한다. 폭 감소는 부수 효과일 뿐이다.

  **로고는 두 구성 모두에서 화면에 하나 있다**(`lg` 미만은 헤더 중앙, 이상은 패널 머리) — 워드마크가 약 65px라 헤더에서 숨겨서 아낄 폭이 거의 없고(320px에서 헤더 바 넘침 0, 로고 중앙 오차 −0.008px 실측), 숨기면 홈 링크가 사라진다.

  검색은 `w-8`에서 `w-full sm:w-64`로 펼쳐진다 — 다만 `sm` 이상의 `w-64`는 선호 폭이지 하한이 아니다. **`sm` 미만에서 검색을 펼치면 헤더를 독점한다** — 버거·로고를 숨기고 한 줄 전체가 입력칸이 된다(좌측에 닫기 버튼). 분기는 CSS로 한다 — `Sheet`와 달리 in-flow 요소라 `sm:` 클래스가 닿는다(JS 분기가 필요 없다). `sm` 이상의 인라인 펼침은 그대로다 — 우측 아이콘 그룹과 펼친 검색은 `min-w-0`을 갖고 있어, 폭이 모자라면 아이콘(`shrink-0`)이 아니라 검색만 줄어든다. **검색 독점은 `sm`(640px) 미만만이다** — 헤더가 세 항목인 640~1023px에서는 검색을 펼쳐도 버거·로고가 남고 입력칸은 3열 안에서 `w-64`다(실측 640·768·1023px: 그룹 256px·입력칸 216px, 헤더 바·문서 넘침 0). 그 구간까지 독점하면 검색 중 버거가 사라져 드로어에 닿을 길이 없어진다.

  **헤더 폭 예산 실측 지침도 구성별로 갈린다** — `lg` 이상에서 아이콘을 더할 땐 패널 펼침·레일 두 상태와 검색 펼침 상태에서 `bar.scrollWidth === bar.clientWidth`를 실측할 것(가장 좁은 칸은 1024px 펼침, 헤더 784px, 안쪽 736px에 필요 559px — 산수. 지금 구성은 그 칸에서 넘침 0 실측). **`lg` 미만에 아이콘을 더하려면 드로어에 넣는 것이 기본이다** — 항목이 셋뿐인 구성에 넷째를 얹는 건 예외로 다룬다.

  실측(패널 개편 때, 스크롤바 중화): `lg` 미만(320·390·640·768·1023) 버거 left 16·16·24·24·24px · 로고 중앙 오차 −0.008px · 넘침 0, `lg` 이상(1024·1100·1279·1280·1440·1512 × 펼침·레일) 헤더 첫 글자 x 펼침 264 · 레일 88px · 헤더 바·문서 넘침 0.
- **좌측 드로어**(`Sheet side="left"`)는 `lg` 미만에서 좌측 패널과 헤더에서 빠진 것을 함께 담는다 — `packages/ui/src/components/sheet.tsx`가 `inset-y-0 left-0 h-full w-3/4 border-r` + `sm:max-w-sm`(384px) + 내장 닫기 버튼을 이미 갖고 있다. 순서: 유형 전환(캐릭터 · 스토리 · "노벨" pill — 로그인과 무관, 노벨 pill은 노벨이 열려 있을 때만) / 구분선 / (로그인 시) 알림 · 구분선 / 패널 내비 / 구분선 / 최근 대화(패널과 같은 머리·행·상태) / 구분선 / (로그인 시) 계정 항목(내 프로필 · 대화 프로필 · 클로버 · 크리에이터 정산 · 설정) · 구분선 · 고객센터 항목 · 구분선 · 로그아웃, 비로그인은 맨 위 "로그인" 행(지금 그대로)과 공개 목적지(고객센터 목적지 중 `isPublic` 항목 — `apps/web/src/shared/config/supportDestinations.ts`)이고, 최근 대화 자리에는 패널과 같은 "로그인하고 보기"가 있다(라벨로 갈린다). 알림이 패널 목록보다 위인 이유: 버거의 점(미확인 알림)이 가리키는 것을 스크롤 없이 찾게 하려는 것이다. 드로어는 `popover` 위라 행의 채움·웰·스켈레톤에 `muted`를 쓰지 않는다(Colors 절). 드로어가 열린 채 `lg` 이상으로 넓히면 닫고 포커스를 패널의 현재 항목(없으면 본문)으로 보낸다 — 버거가 `lg` 이상에서 `display:none`이라 기본 복귀 대상이 없다. **`ProfileMenu`를 드로어에 그대로 넣지 않는다** — 시트 안에서 Radix 드롭다운을 다시 여는 중첩이고, `apps/web/CLAUDE.md` 메뉴 · 모달 절이 이미 "열린 Sheet는 포커스 트랩과 바깥 클릭 차단까지 걸어 인라인 패널과 공존할 수 없다 — 둘 중 하나만 마운트되어야 한다"고 적어 뒀다. 목적지 목록은 **한 곳에서만** 정한다(`ProfileMenu`가 쓰는 것과 같은 소스) — 안 그러면 한쪽에만 항목이 추가되는 실패 모드다(`toContentStatusTags` 선례). **트리거는 드로어 위젯이 소유한다**(자기완결 위젯) — 호출부(`Header`)는 컴포넌트 하나만 배치하고 열림 상태를 알지 않는다.
- **미확인 알림은 버거에 점으로 승격한다** — 개수가 아니라 점이다(버거는 여러 항목의 수납구라 숫자를 달면 무엇의 개수인지 모호해진다), 색은 `foreground`다(처음엔 `primary`로 정했다가 정정했다 — `primary`는 무채색으로 충분한 신호에 유일한 유채색 예산을 쓰는 셈이라 기각했다, `MobileNavDrawer.tsx`의 `BurgerButtonWithUnreadDot`).
  구현은 `widgets/header/ui/MobileNavDrawer.tsx`다. 드로어는 버거로 열리고 Esc·스크림으로 닫히며, 닫은 뒤 포커스가 버거로 돌아간다(열린 동안은 포커스 트랩). 버거 점은 미확인 알림이 있을 때만 보인다.
- **채팅 화면은 뷰포트 고정이다**: `h-below-header`(`globals.css`의 `@utility`, `calc(100dvh - 3.5rem)`). 이 `3.5rem`은 헤더의 `h-14`를 수동으로 미러링한 값이므로 **헤더 높이를 바꾸면 그 유틸리티 한 곳, 그 짝인 `min-h-below-header`(`globals.css`의 `@utility`, 인증 화면 — 로그인·가입·비밀번호 찾기/재설정·온보딩 — 이 헤더 아래 보이는 영역에 폼을 가운데 놓는 최소 높이), 같은 계산의 `max-h-below-header`(`globals.css`의 `@utility`, 이미지 스튜디오 옵션 시트가 헤더 아래까지만 자라게 하는 최대 높이), 아래 `ChatMorePanel`의 `top-below-chat-header`(`globals.css`의 `@utility`, `118px`)를 함께 고쳐야 한다**(호출부는 `ChatRoomView` 3 · `PreviewSessionView` · `BuilderLayout` · `BuilderPreview` · `ImageStudioShell` · `MediaBookGridPane` · `NovelBoardPage` 4). 2026-09-11 재측정 — 그 전까지 이 줄은 "5곳"이라 적혀 `BuilderPreview`를 빠뜨리고 있었다. **2026-09-14 재측정 — "6곳"도 틀렸다**, `ImageStudioShell`이 빠져 있었다.
- **채팅 더보기 패널은 1024px 이상에서 인라인 사이드바다**(`w-72`, `border-l border-border`, `bg-card`, 채팅 헤더 아래부터 바닥까지). 이것은 크롬이 아니다 — 기본이 닫힘이고 채팅 라우트에만 있으며 ⋮로 여는 일시적 패널이다. 오버레이가 아니라 채팅 컬럼과 폭을 나눠 갖는 이유는 **열어둔 채로 대화를 계속 읽고 보낼 수 있어야** 하기 때문이다. 분기는 `lg:` 클래스가 아니라 JS(`useMedia`)로 한다 — `Sheet`는 body로 포털돼 부모 클래스가 닿지 않고, 열린 `Sheet`는 포커스 트랩까지 걸어 인라인 패널과 공존할 수 없다.
- **1024px 미만에서 같은 패널은 바닥에서 올라오는 드롭업이다**(`Sheet side="bottom"` + `top-below-chat-header` + `rounded-t-xl`). 우측 시트가 아니라 드롭업인 이유는 **누구와 대화 중인지가 계속 보여야** 하기 때문이다 — 시트 상단을 채팅 헤더 바로 아래에 붙여 아바타·캐릭터명·방 이름을 남긴다. 그 `118px`는 전역 헤더 `h-14`(56) + border 1 + 채팅 헤더 60 + border 1을 실측한 값으로, 위의 `calc(100dvh-3.5rem)`와 같은 계열의 수동 미러링이다(헤더 높이를 바꾸면 여기도 함께 고친다). 전역 헤더는 채팅 헤더 위에 있으므로 함께 남는다 — 둘을 따로 고를 수 없다. 오버레이 스크림은 그 위를 덮으므로 헤더는 보이되 흐려진다(의도된 모달 표현).

### Status badges
- **Shape:** `inline-flex items-center rounded-full px-2 py-0.5 text-badge font-medium`. 전용 `Badge` 프리미티브는 없고 각 자리에서 손으로 조립한다(크기만 토큰이다 — §Typography의 Badge 티어).
- **중립 상태(공개/링크공개/비공개/미등록, 문의 대기/답변완료):** `border border-border` — **채움이 아니라 윤곽이다**. `bg-muted` 채움은 카드 표면과 같은 값이 되는 순간이 반드시 있어(정지 `bg-card` 카드 위에서, 또는 `hover:bg-muted`가 걸린 카드의 hover에서 — 둘 다 실측 1.0000:1) 알약이 통째로 사라진다. 윤곽은 hover에서도 살아남는다(다크 1.3076 / 라이트 1.2699). 결과적으로 **타입=채움 / 상태=윤곽**으로 형태가 갈려 위계가 생긴다.
- ⚠️ **프론트매터의 `badge-status`는 이 사실을 온전히 표현하지 못한다**(2026-09-11). 한때 `backgroundColor: "{colors.muted}"`로 적혀 있어 **실제 구현과 정면으로 달랐고**(실제는 채움 없는 윤곽), 지금은 `"transparent"`로 고쳤다. 다만 그 스키마에 `borderColor` 슬롯이 없어 **윤곽 자체는 여전히 적을 수 없다** — 이 절의 산문이 단일 진실이다. 프론트매터만 보고 배지를 재현하지 말 것.
- **중립 상태 안의 위계는 잉크 명도로 만든다.** 기본은 `text-muted-foreground`, **사용자가 읽을 게 생긴 상태만** 밝기 천장 `text-foreground`로 올린다 — 지금은 문의의 `답변완료` 하나뿐이다(`entities/inquiry/ui/inquiryStatusBadge.ts`의 `INQUIRY_STATUS_BADGE_INK`). 색으로 가르지 않는 것은 PRODUCT.md가 "UI 자체(배경/텍스트/버튼/배지)는 무채색"으로 못박았기 때문이고, 이 시스템의 깊이는 원래 명도 사다리가 만든다.
  - **`hover:bg-muted` 카드 위가 최악이고, 라이트의 `대기`가 AA 경계에 가장 가깝다**(스크린샷 픽셀 디코드 실측, `/ui-demo`): `대기` 다크 6.7374→**6.1553**, 라이트 5.2511→**4.8165**(AA 여유 0.32뿐 — hover 표면을 더 어둡게 하거나 `muted-foreground`를 더 밝히면 깨진다). `답변완료`는 다크 15.8622→14.4917, 라이트 17.2244→15.7988로 여유가 크다. 윤곽 자체는 다크 1.4312→1.3076, 라이트 1.3845→1.2699다.
- **이용제한:** `bg-destructive/10 text-destructive-text` — 틴트, 채움 아님.
- **타입(캐릭터/스토리):** `bg-secondary text-secondary-foreground` + 14px 아이콘.
- **삭제:** 배지가 아니라 전체 패널 빈 상태로 표현한다(`ContentUnavailableState`) — 아이콘 + 제목 + 설명.
- 상태 배지는 소유자에게만 렌더한다.

### Layout containers
페이지 컨테이너의 표준 관용구는 `mx-auto flex max-w-* flex-col gap-* px-4 sm:px-6 py-10`이다. **헤더 안쪽 바와 같은 값(`px-4 sm:px-6`)인 이유**: `lg` 미만에서는 헤더 안쪽 바와 `max-w-5xl` 컬럼이 둘 다 뷰포트를 꽉 채우므로(뷰포트가 1024px 미만이라 상한에 닿지 않는다) 패딩이 같아야 버거 left와 본문 콘텐츠 x가 같은 x에 선다(홈 실측, 버거 left · 본문 콘텐츠 x: 320·390px 16 · 16, 640·768·1023px 24 · 24). 그보다 좁은 `max-w-*` 컬럼은 뷰포트가 상한을 넘으면 가운데로 들어가 두 x가 갈린다. max-width는 콘텐츠 밀도에 따라 고른다: 그리드형 목록 `max-w-5xl`, 프로필 `max-w-4xl`, 폼·상세·대화방 목록(`/chats`, `widgets/chat-room-list`) `max-w-2xl`, **설정(`/mypage`) `max-w-md`**. **빌더는 lg 미만이면 가운데 정렬된 `max-w-2xl`, lg 이상이면 왼쪽부터 채우는 2단 그리드다**(`features/build-common/ui/BuilderLayout.tsx`). lg 미만은 폼과 미리보기 중 하나만 보이고, 미리보기를 열면 상한 없이 전체화면이다. lg 이상에서는 `main`이 상한과 가운데 정렬을 걷고(`lg:max-w-none`) 트랙이 `minmax(0,42rem) 1fr`이다 — 폼 열은 42rem(`max-w-2xl`과 같은 672px)이고, 미리보기 칸은 `1fr` 트랙 안에서 `max-w-4xl`(896px)로 묶여 그 오른쪽은 빈다. 이 상한은 실제 채팅 문단 상한(`max-w-3xl`, 768px)에 좌우 `px-6`을 더한 폭을 담는 가장 작은 Tailwind 값이다(`max-w-3xl`이면 칸 안 문단이 720px에서 멈춘다). 그래서 칸이 상한에 닿는 넓은 화면(약 1600px 이상 = 672 + 24 + 896)에서만 대화 미리보기의 줄 길이가 실제 채팅과 같고, 그보다 좁으면 칸이 상한에 못 미쳐 줄이 짧다. **상한은 트랙(`minmax(0,…)`)이 아니라 칸에 건다** — 두 트랙이 모두 고정 상한이면 그리드가 남는 폭을 두 트랙에 나눠 키워 1024~1368px에서 폼 열이 42rem보다 좁아진다. `1fr` 트랙은 폼 열이 42rem을 채운 뒤에야 자란다(1024·1280px 실측 폼 열 672px). 칸 안의 대화 미리보기(`PreviewSessionView`)·카드 미리보기·미디어 북 배치표(`MediaBookGridPane`)는 모두 칸 폭을 따른다 — `PreviewSessionView`와 `PreviewCloseHeader` 안쪽 행의 `max-w-5xl`은 칸(최대 896px)보다 커서 효력이 없다. 미디어 북 탭에서는 오른쪽 열에 대화 대신 배치표가 서고(대화는 숨겨 둔 채 마운트를 유지한다), lg 미만의 미리보기 화면도 그 탭에서는 배치표다. 빌더 라우트에는 전역 헤더도 좌측 패널도 없다(Navigation 절 빌더 예외) — 대신 상단바(`BuilderTopBar`)는 안쪽 바가 뷰포트를 꽉 채운다(`px-4 sm:px-6`만, max-width 없음 — 전역 헤더 안쪽 바와 같은 클래스). 상단바는 `isPreviewOpen`을 받지 않아 미리보기를 열고 닫아도 움직이지 않는다. **lg 이상에서는 탭 목록 left가 어느 폭에서나 뒤로가기 버튼 left와 같다(drift 0)** — 상단바와 폼 열이 둘 다 뷰포트 왼쪽 끝에서 같은 `px-4 sm:px-6`으로 시작하기 때문이라, 한쪽 패딩을 바꾸면 다른 쪽도 함께 바꿔야 한다. 실측(뒤로가기 버튼 left / 탭 목록 left): 1024 · 1280 · 1440 · 1920px 모두 24/24. lg 미만은 본문이 `max-w-2xl`로 가운데 정렬돼 뷰포트가 672px를 넘으면 두 left가 갈린다(820px 24/98) — 의도된 것이다. **세로 여백도 lg 이상에서만 줄인다**: 폼 열 윗여백 `lg:pt-6`으로 상단바 → 탭 목록이 24px이고, 두 셸의 `<Tabs className="lg:gap-0">`로 탭 목록 → 첫 내용은 각 탭 본문 컴포넌트 루트의 `py-6` 하나(24px)다. 그래서 **탭 본문은 조기 반환하는 빈 상태까지 루트에 `py-6`을 가진다** — 스탯·엔딩 탭의 '먼저 시작설정 탭에서…' 상자를 `py-6` 래퍼로 감싼 이유다(없으면 lg 이상에서 탭 목록과 점선 상자가 맞붙는다). lg 미만은 페이지 표준 관용구(`py-10`)와 `Tabs` 기본 `gap-2` 그대로다. `BuilderTopBar`를 렌더하는 다섯 곳 중 `BuilderLayout`을 쓰는 것은 두 셸(`StoryBuilderShell`·`CharacterBuilderShell`)뿐이다. `pages/builder/ui/BuilderPage.tsx`의 스켈레톤·초안 오류 상태는 `max-w-2xl` 리터럴을 직접 갖되 `lg:mx-0`(스켈레톤은 `lg:pt-6`도)으로 lg 이상에서 셸과 같은 자리에 선다 — 로딩에서 셸로 넘어갈 때 내용이 옆으로 튀지 않게 하려는 것이다(1440px 실측: 스켈레톤 첫 막대 left/top 24/80 = 셸 탭 목록 자리). `/builder` 타입 선택 화면(`BuilderTypeSelectPage`)은 `BuilderLayout`을 쓰지 않고 `mx-auto max-w-2xl` 가운데 정렬이라 뒤로가기 버튼 대비 콘텐츠 left가 390px 0 · 1024px −176 · 1440px −384로 벌어진다. **대화방(`/chat/$roomId`)도 다른 라우트와 같은 `max-w-5xl` 컬럼에 산다** — 근거는 로고 정렬이 아니라 **본문 컬럼 규약**이다(그리드형 목록과 같은 폭, 위 표준 관용구). 전역 헤더 안쪽 바가 놓인 열을 꽉 채우고 `lg` 이상에서는 로고가 좌측 패널 머리로 옮겨 가, 로고 x는 더 이상 비교 대상이 아니다. 대화방 컬럼이 한때 전폭이었고 그게 의도라고 여기 적혀 있었지만 틀렸다 — 패딩만 헤더와 맞춰 두면 `padding-left`는 24px로 같아도 콘텐츠 x는 어긋난 채고, 헤더가 `max-w-6xl`에서 `max-w-5xl`로 내려오면서 로고가 오른쪽으로 64px 밀려 그 격차가 **144.5px → 200.5px로 넓어졌다**(1425px 실측). **컬럼 제한은 셸 바깥이 아니라 채팅 컬럼과 사이드바를 담는 flex 행에 건다**(`mx-auto flex w-full min-h-0 max-w-5xl flex-1`). 이렇게 해야 더보기 사이드바(`ChatMoreSidebar`)가 오버레이가 되지 않고 채팅 컬럼과 폭을 나눠 갖는 in-flow `<aside>`로 남으면서(열어둔 채로 입력해야 해서 포털+모달 전제인 Sheet를 쓸 수 없다, §Navigation) 채팅 컬럼이 그 행의 **첫** flex 아이템이라 사이드바를 여닫아도 좌측 콘텐츠 시작점이 움직이지 않는다 — 폭은 오른쪽에서만 줄어든다. **`w-full`을 빼면 안 된다**: flex 컬럼의 자식에 `margin-inline: auto`가 붙으면 명세상 stretch가 꺼져 폭이 shrink-to-fit으로 붕괴한다(1200px 부모에서 8.2px vs 1024px, 실측). 실측(1425px, **헤더 내부 바가 `max-w-5xl`이던 동안의 값**): 로고 x와 채팅 헤더·메시지 영역·입력창의 콘텐츠 x가 모두 **224.5px, drift 0.00**이었고 사이드바 개폐 4회 × 50프레임 동안 문서 넘침 0이었다. 1265·1024·753·390px에서도 drift 0.00이었다. 지금 `lg` 경계(1024)에서 채팅은 레일로 시작하므로 행 960px 안에서 사이드바 288px / 메시지 컬럼 672px이고, 사용자가 패널을 펼치면 행 784px 안에서 메시지 컬럼 496px다(실측). **가로로 화면을 가로지르는 선은 y=56의 한 줄이다** — `lg` 미만은 헤더 `border-b`, `lg` 이상은 패널 머리 `border-b`와 헤더 `border-b`가 같은 높이에서 이어진 것이다. 세로로 가로지르는 선은 `lg` 이상 패널의 `border-r` 하나다. 채팅 헤더의 `border-b`는 `<header>`가 아니라 안쪽 컬럼 div에 걸어 선이 화면이 아니라 컬럼 경계를 따르게 한다(1440px·레일 실측: y=56 선 1440(패널 머리 64 + 헤더 1376) / 채팅 헤더 선 1024 / 입력 바 1024px). **단 아래 선들과 길이가 같아지는 건 사이드바가 닫혀 있을 때뿐이다** — 열면 채팅 헤더 선은 행 전체(1024px), `StatGaugePanel`·버전 배너·입력창의 선은 채팅 컬럼만(736px, 같은 실측에서 사이드바 288px) 덮는다. 헤더가 채팅 컬럼과 사이드바 둘 다의 위에 있으므로 이게 맞는 동작이다. 빌더 미리보기(`PreviewSessionView`)도 같은 셸이라 같은 규칙을 따른다(사이드바가 없어 행 대신 `flex-col` 래퍼다). 인증 화면만 다른 셸을 쓴다(`min-h-screen items-center justify-center px-4 py-12` + `sm:max-w-sm` 카드) — **여기는 손댈 것이 없다**: 패딩이 실제로 닿는 구간은 뷰포트 480px 이하뿐이고(448 + 32), 그 구간은 전부 `sm:` 미만이라 새 통일값과 이미 16px로 같다. 480px 초과에서는 카드가 중앙 정렬돼 패딩이 관여하지 않는다(실측: `sm` 미만에서 `/login`·`/signup`도 다른 라우트와 drift 0.00). **인증 화면에 브랜드 마크를 따로 두지 않는다** — 전역 크롬이 인증 라우트에도 마운트되어 로고가 이미 화면에 있으므로(`lg` 미만은 헤더, 이상은 패널 머리 — 크롬을 그리지 않는 화면은 Navigation 절의 셋) 카드 위에 워드마크를 얹으면 같은 단어가 한 화면에 두 번 나온다. `lg` 이상에서 인증 카드는 패널 오른쪽 영역의 가운데에 놓인다(뷰포트 가운데에서 패널 폭의 절반만큼 오른쪽).

**컬럼은 그 안에서 가장 넓은 *고대비 잉크*에 맞춘다 — 가장 넓은 컨트롤이 아니다.** 이 시스템에는 본문 컬럼을 두르는 카드도 보더도 없어 컬럼 경계가 화면에 그려지지 않는다(`lg` 이상 패널의 `border-r`는 컬럼이 아니라 크롬의 경계다 — 그래서 중심의 기준은 뷰포트가 아니라 패널 오른쪽 영역이다). 그래서 사용자가 중심을 판정하는 기준은 박스가 아니라 **텍스트**다. `w-full` 컨트롤(인풋·폼)은 컬럼이 얼마나 넓든 컬럼을 채우므로 폭 선택의 근거가 되지 못한다 — **항진명제**이기 때문이다(`/mypage` 비밀번호 인풋은 `max-w-md`에서 400px, `max-w-2xl`에서 624px로 **양쪽 다 콘텐츠 박스를 정확히 채운다**). 근거는 텍스트 쪽이다 — 산문은 늘어난 폭을 줄바꿈으로 흡수해 마지막 줄 오른쪽에 빈자리를 남길 수 있고, 잉크가 컬럼만큼 늘지 않으면 남는 폭이 오른쪽에 쌓여 잉크 중심이 왼쪽으로 밀린다. 한때 `/mypage`가 그 실례였다(콘텐츠 박스 400→624px(+224)에 잉크 391.13→450.11px(+59), 뷰포트 중심 대비 `max-w-md` −4.44px · `max-w-2xl` −86.95px, 1280px A/B 실측). 화면 내용이 바뀐 지금은 같은 A/B에서 잉크가 377.86→591.58px(+213.7)로 거의 같이 늘어, 영역 중심 대비 `max-w-md` **−11.07px** · `max-w-2xl` **−16.21px**다(1280px, 좌측 패널 펼침·레일 같은 값, `max-w-2xl`은 클래스를 임시로 바꿔 잰 값) — `max-w-md`가 가깝다는 방향은 같지만 차이가 5px라, 이 화면이 `max-w-md`인 근거는 이제 중심 오차가 아니라 넓은 컬럼을 요구하던 초안 그리드가 `/my`로 옮겨 간 것이다(`MyPagePage.tsx` 주석). **박스 자체는 두 폭 모두 정확히 중앙이다** — 그런데 그 박스를 그리는 유일한 선인 인풋 보더가 저대비라 눈에 남는 건 텍스트뿐이다. 목록에서 가장 넓은 항목이 사라지면 컬럼도 함께 줄인다.

**간격은 gap 하나로만 만든다** — `space-y-*`와 `divide-*`는 앱 전체에서 **0회** 사용이며, 레이아웃은 100% `flex flex-col gap-*`이다. 가장 많이 쓰이는 값은 `gap-1.5`(6px, 라벨↔인풋)와 `gap-2`(8px, 버튼 행)다.

**Tailwind 브레이크포인트는 `sm`(640px)과 `md`(768px) 둘뿐이었다.** `lg:`(1024px) 클래스는 **빌더 레이아웃 6개 파일, 빌더 미디어 북 탭 2개 파일, 상세화면 하단 고정 CTA 2개 파일, 이미지 스튜디오 1개 파일(`widgets/image-studio/ui/ImageStudioShell.tsx` — 3열, 그 열이 대신하는 좁은 화면 전용 진입점(시트 트리거 줄·스타일 선택 버튼)의 `lg:hidden`, 결과 영역의 스크롤 여백), 작성 가이드 단계 페이지 3개 파일(`pages/creation-guide/ui/CreationGuideStepPage.tsx`의 본문 폭 · `GuideFieldBlock.tsx`의 설명 ↔ 칸 그림 2열 · `GuideBadComparison.tsx`의 좋은 예/나쁜 예 나란히 — 빌더 2단과 같은 이유로 넓은 화면의 빈 폭을 그림에 쓴다), 클로버 상품 안내 1개 파일(`pages/clover-pricing/ui/CloverPricingPage.tsx` — 문서 폭 `max-w-2xl` 컬럼을 `max-w-4xl`로 넓혀 상품과 쓰임새를 2열로 나란히 두고, 아래 정책 문장은 `max-w-prose`로 묶어 줄 길이를 문서 화면과 같게 둔다 — 1280px 실측 620px, 법적 문서 본문 624px), 좌측 패널 셸 2개 파일(`widgets/header/ui/Header.tsx` — 로고·버거 `lg:hidden`, `lg:flex`, 유형 탭·아이콘 `hidden lg:*` / `pages/home/ui/HomePage.tsx` — 첫 행 유형 토글 `lg:hidden`·유형 이름 `hidden lg:block`)에 있다**(주석에만 `lg:`가 나오는 파일 — `BuilderPreview`·이미지 스튜디오 레일 둘·스타일 선택 버튼(`features/generate-images/ui/GenerateImagesStyleSummaryButton.tsx`, 숨김 클래스는 셸이 넘긴다)·`useIsChatMoreSidebarLayout`·좌측 패널 마운트 훅 `useIsSidePanelLayout` — 은 세지 않는다. 패널 자체와 드로어는 JS 마운트·`Header`가 넘기는 `lg:hidden`이라 `lg:` 클래스가 없다). **`xl:`(1280px) 클래스는 저장소에 둘이다** — 이미지 스튜디오 우열 폭 `w-80 xl:w-96`(`ImageStudioShell.tsx`)으로 1280px 이상에서 우열 안 스타일 타일(3열)을 키우는 것, 그리고 소설 편집 보드 옆 패널 폭 `w-md xl:w-lg`로 1280px 이상에서 편집 본문 한 줄을 늘리는 것이다(1024px에서 넓히면 캔버스가 576px 아래로 줄어든다). lg 구간에서 넓히지 않는 것은 1024px에서 우열이 넓어지면 중앙 열이 줄어 생성 결과가 좁아지기 때문이다. 빌더가 앱 최초의 `lg:` 도입이었다. 빌더 여섯은 2단 그리드·미리보기 칸 상한·윗여백을 쥔 `features/build-common/ui/BuilderLayout.tsx`, lg 이상에서 필요 없어지는 모바일 전용 [미리보기]/닫기 버튼을 `lg:hidden`으로 숨기는 `features/build-common/ui/BuilderTopBarActions.tsx`·`features/build-common/ui/PreviewCloseHeader.tsx`(미리보기 열의 대화·카드와 미디어 북 배치표가 함께 쓰도록 `widgets/builder-preview`에서 옮겼다), 스켈레톤·초안 오류 상태를 lg 이상에서 왼쪽에 붙이는 `pages/builder/ui/BuilderPage.tsx`(`lg:mx-0`·`lg:pt-6`), 탭 목록과 첫 내용 사이의 `Tabs` 간격을 lg 이상에서 걷는 `widgets/build-story/ui/StoryBuilderShell.tsx`·`widgets/build-character/ui/CharacterBuilderShell.tsx`(`lg:gap-0`)다. 미디어 북 둘은 칸 상세 머리의 스크롤 여백(`lg:scroll-mt-6`)과 좁은 화면 전용 '배치표로 돌아가기' 버튼(`lg:hidden`)을 가진 `widgets/build-story/ui/MediaBookCellPanel.tsx`, 상세 자리표시의 '오른쪽' 방향어(`lg:inline`)와 좁은 화면 전용 '배치표에서 칸 고르기' 버튼·안내(`lg:hidden`)를 가진 `widgets/build-story/ui/MediaBookTab.tsx`다. 상세화면 둘은 플레이 CTA를 lg 미만에서만 하단 고정으로 띄우는 `widgets/content-detail/ui/ContentDetailView.tsx`와, 그 바 위로 올라오는 아래 패딩을 lg 미만에서만 지는 `widgets/site-footer/ui/SiteFooter.tsx`(`lg:pb-4-safe`)다. 공용 카드 그리드(`entities/content`의 `ContentCardGrid`)는 뷰포트가 아니라 **컨테이너 쿼리**로 열을 가른다 — 패널이 펴지고 접히며 본문 폭이 바뀌어서다(admin 본문 그리드와 같은 이유, Navigation 절). 경계는 그리드 폭 37rem(592px)·45rem(720px)으로, 뷰포트 `sm`·`md`에서 거터를 뺀 폭이라 지금까지의 열 수가 그대로 나온다. 다른 곳은 하나 — `sm` 경계에서 거터가 16→24px로 늘어 그리드 폭이 607→592px로 줄어드는 탓에 뷰포트 624~639px가 한 단계 일찍 늘어난다(정사각 3열 189~194px, 세로 4열 139~143px — 640px와 같은 값). 최대 열(정사각·혼합 4, 세로 5)에서 멈추는 것은 여전히 의도다. 빌더 미리보기 칸은 이 그리드가 아니라 칸 폭으로 열 수를 정하는 `auto-fit` 그리드다. 패널이 있는 `lg` 이상에서 홈 세로 카드는 1024px 펼침 137.6px(그리드 736px, 작가명 6.1자) · 레일 172.8px(그리드 912px)이고 열은 늘 5다(실측). 채팅 더보기 패널의 1024px 분기(§Navigation)는 CSS가 아니라 JS 미디어쿼리인데, `Sheet`가 body로 포털돼 부모의 `lg:` 클래스가 닿지 않고 열린 `Sheet`가 포커스 트랩까지 걸어 인라인 패널과 공존할 수 없기 때문이다 — 빌더 프리뷰 열은 포털 없는 in-flow 요소라 그 제약이 없어 CSS `lg:`로 분기한다. 소설 편집 보드의 1024px 분기(캔버스 ↔ 세로 흐름 목록, 옆 패널 ↔ 목록 자리의 패널, `widgets/novel-board`의 `useIsNovelBoardCanvasLayout`)도 JS다 — 캔버스 라이브러리를 좁은 화면에서 마운트하지도 내려받지도 않아야 해서, CSS로 숨겨 둘 수 없다. 옆 패널 폭만 CSS(`w-md xl:w-lg`)이고, 그 패널은 `lg` 이상에서만 그려진다. **`lg:` 분기의 폭 근거는 이제 좌측 패널 상태에 기댄다** — 패널이 있는 화면(채팅·이미지 스튜디오·작성 가이드 단계·클로버 상품)에서 `lg:`가 켜지는 1024px 뷰포트의 본문은 레일이면 960px, 펼침이면 784px다. 채팅·스튜디오는 늘 레일로 들어오고, `lg`~`xl`은 저장값이 없으면 레일이다. 사용자가 펼치면 1024px에서 스튜디오 중앙 열은 224px까지 줄어든다(실측, 레일이면 400px — 그래서 바깥에서 들어올 때 레일로 시작한다). 빌더·보드는 패널을 그리지 않아 위 실측이 그대로다.

### Motion
- **모션 라이브러리는 없다.** `tw-animate-css` + Tailwind 유틸리티만 쓴다 — 예외 하나는 소설 화 읽기 화면의 쪽 넘김으로, 스크롤 위치(`scrollLeft`)는 CSS 전환으로 움직일 수 없어 `requestAnimationFrame` 몇 줄로 직접 움직인다(라이브러리는 들이지 않는다). 이 시스템에 코레오그래피는 존재하지 않는다.
- **지속시간은 100-300ms**: 팝오버 100ms, 스텝 전환·검색 확장 200ms, 스탯 게이지 300ms. `ease-out`.
- **모든 모션은 `motion-safe:` 접두사로 가드한다** — 어두운 방에서 갑작스러운 움직임은 놀람이다. 새 애니메이션을 추가할 때 `motion-safe:`를 빼먹지 말 것. `packages/ui`의 프리미티브 12개는 전수 게이팅돼 있고(dialog·alert-dialog·sheet·dropdown-menu·select·button·toggle·switch·tabs·input·textarea·checkbox·table), `reduce`에서 `animation-name: none` · `transition-duration: 0s`가 되는 것이 실측돼 있다. 좌측 패널과 함께 더한 `tooltip`도 등장과 시간(`duration-*`)을 모두 `motion-safe:`로 가드한다.
  - **`duration-*`도 함께 가드한다.** `duration-100`은 `transition-duration`까지 세팅하는데 CSS의 `transition-property` 초깃값이 `all`이라, 애니메이션만 끄면 `reduce`에서 `transition: all 0.1s`가 살아남는다.
  - **호출부에서는 못 끈다** — `motion-reduce:animate-none`을 얹어도 `data-open:` 변형의 속성 선택자가 특이도에서 이긴다. 프리미티브에서 가드하는 것 말고 방법이 없다.
  - **예외는 진행 표시다** — 로딩 스피너(`animate-spin`)·스켈레톤(`animate-pulse`)·**타이핑 인디케이터**(`animate-pulse`)는 멈추면 "멈춘 UI"로 읽히므로 가드하지 않는다. 장식·전환은 가드하고 진행 표시는 남긴다. **타이핑 인디케이터가 여기 속하는 이유**: 멈춘 점 세 개는 "AI가 응답을 멈췄다"로 읽힌다 — 어떤 상태인지 알리는 표시가 아니라 "지금 답을 만들고 있다"는 진행 표시라서, 예외의 근거가 스피너·스켈레톤보다 오히려 세게 적용된다.
  - **직접 조작은 모션이 아니다** — 사용자가 끄는 동안 화면이 손가락·마우스를 그대로 따라가는 것(소설 화 읽기 화면의 쪽 끌기, 네이티브 스크롤과 같은 종류)은 사용자가 스스로 만드는 움직임이라 놀람이 아니고, 끄면 손짓에 화면이 반응하지 않는 고장으로 읽힌다. 그래서 가드하지 않는다. 가드 대상은 손을 뗀 뒤 시스템이 이어서 움직이는 부분이다 — 끌기를 놓은 뒤 가장 가까운 쪽으로 맞춰 들어가는 이동은 전환이라 `reduce` 에서 즉시 맞춘다.
- 상태 전달만 한다: 스텝 전환, 팝오버 열림, 게이지 변화. 장식적 등장 연출은 금지.
- **소설 화 읽기 화면**: 위·아래 바의 등장·퇴장은 장식 전환이라 가드한다(`motion-safe:` transform·opacity, 200ms `ease-out` — reduce 에서는 즉시 나타나고 사라진다). 페이지 모드의 쪽 넘김(넘김 버튼·탭·휠·키보드 `←`/`→` 등)은 어느 쪽으로 갔는지 알리는 전환이라 같은 규칙이다 — 250ms `ease-out` 가로 이동이고 `prefers-reduced-motion: reduce` 면 즉시 바뀐다. 끌기를 놓은 뒤 맞춰 들어가는 이동은 남은 거리에 비례해 80~250ms 다 — 거의 다 끌어 놓은 쪽이 고정 250ms 동안 들어오면 늘어져 보이고, 80ms 보다 짧으면 맞춰 들어가는 움직임이 아니라 순간이동으로 보인다(그래서 위의 100-300ms 범위보다 짧을 수 있다). 쪽 이동 슬라이더·`Home`/`End`로 옮길 때와 스크롤 모드의 진행 막대는 진행 표시 예외가 아니라 위치 표시라 애초에 전환을 두지 않는다. 끄는 동안 쪽이 손을 따라오는 것은 위의 직접 조작이다. 판형 배율은 창 크기·회전에 따라 즉시 바뀐다 — 전환을 두지 않는다(창을 끄는 동안 글자가 출렁이며 따라오는 것은 놀람이다). 바를 여닫을 때 판형은 움직이지 않는다(바 자리가 늘 비어 있어서다). 한 장 ↔ 펼침, 페이지 ↔ 스크롤(배율이 하한 밑으로 내려가 스크롤 모드로 보일 때 포함) 전환도 즉시 바꾸고 읽던 문단으로 돌아간다. 그 전환을 알리는 한 줄 안내는 토스트라 등장·퇴장을 sonner 가 `prefers-reduced-motion` 에서 스스로 끈다.
- **좌측 패널 폭**: 사용자가 토글로 접고 펼 때만 200ms `ease-out` 폭 전환(`motion-safe:`로 가드 — `duration-*` 포함). 채팅·스튜디오 진입이나 창 크기 변화가 바꾸는 접힘은 즉시 — 본문 폭이 같은 순간 바뀌어 전환을 두면 새 화면이 출렁인다. 레일 툴팁은 팝오버와 같은 100ms.
- **코드 블록 복사의 피드백은 토스트 하나다**(`copyCodeToClipboard` — 성공 "코드를 복사했어요.", 실패 "코드를 복사하지 못했어요. 직접 선택해 복사해 주세요."). 버튼 아이콘을 체크로 바꾸는 식의 자리 애니메이션은 두지 않는다. 토스트의 등장·퇴장은 sonner가 `prefers-reduced-motion`에서 스스로 끄고(`transition: none; animation: none`), 복사 버튼의 hover 전이는 `Button` 프리미티브의 `motion-safe:transition-all`이 가드한다 — 호출부에 새 모션은 없다(Chat Notation 절의 코드 블록).

## 6. Chat Notation (채팅 표기)

**채팅 메시지 본문을 어떻게 적고 어떻게 그리는지의 유일한 명세다.** 렌더러 테스트 셋(`apps/web/src/entities/chat-room/lib/chatMarkdown.test.ts`·`ui/ChatMarkdown.test.ts`·`model/stripChatNotation.test.ts`)의 사례표가 이 절과 같아야 하고, 표기 규칙을 바꾸면 둘을 함께 고친다. 구현은 `entities/chat-room`의 `model/chatNotationSyntax.ts`(별표 짝짓기·줄 머리 판정 — 본문과 미리보기가 공유), `lib/chatMarkdown.ts`(파서 설정·보정), `ui/ChatMarkdown.tsx`(스타일), `ui/MessageBubble.tsx`(메시지 틀)다.

**적용처**: 채팅방(`ChatRoomView`)의 메시지·스트리밍·에필로그, 빌더 미리보기(`PreviewSessionView`), 엔딩 컬렉션 모달의 에필로그. **약관·공지가 쓰는 공용 `packages/ui` `markdown.tsx`와는 다른 렌더러다** — 그쪽은 표·제목·링크가 필요해서 채팅 부분집합으로 바꿀 수 없다. admin의 대화 조회 화면(`ChatMessagesPage`)은 운영 확인용이라 원문 글자를 그대로 보여 준다.

### 원문 규칙
- **`*…*`로 감싼 구간이 지문(서술·행동), 나머지는 전부 대사다.** 판정 기준은 별표 하나뿐이다.
- **따옴표는 판정에 쓰지 않는다** — `"…"`는 대사 색의 글자 그대로 남는다. 지문 안에 따옴표가 들어가도(`*"안녕"*이라고`) 지문이다.
- **괄호는 파싱하지 않는다** — `(조금 무섭다)`는 괄호째 대사 색 글자다.
- `**…**`는 굵게, `***…***`는 굵은 지문이다. 별표 네 개 이상 런도 표지다 — 파서처럼 **짝수면 굵게, 홀수면 굵은 지문**이다. 파서가 짝지은 `****굵게****`도, 파서가 한국어 flanking 때문에 못 짝지어 재짝짓기로 넘어온 `****"굵게"****라고`도 굵게로 보인다. 양옆이 공백인 런(`안녕 **** 반가워`)은 다른 길이와 마찬가지로 글자다.
- `\*`는 별표 글자다(짝짓기에 참여하지 않는다).
- 한 줄 바꿈은 줄바꿈 그대로(`<br>`), 빈 줄은 새 문단이다. 빈 줄이 여럿이어도 문단 경계 하나다.

### 렌더
- **지문**: 별표를 지우고 `text-muted-foreground`, **이탤릭 없이**(`not-italic`) 그린다. Pretendard에는 이탤릭 face가 없다 — 이 앱이 싣는 `pretendardvariable-dynamic-subset.css`의 `@font-face` 92개가 전부 `font-style: normal`이라, `italic`을 주면 브라우저가 정체 글리프를 기울인 **합성 오블리크**를 만든다. 한글 글리프가 비스듬히 깨져 보이므로 지문과 대사는 기울기가 아니라 명도로만 가른다.
- **대사**: 컨테이너의 `text-foreground` 그대로다.
- **굵게(`**`)**: `font-semibold`. 지문 안에 있으면 지문 색을 그대로 물려받는다.
- **본문 컨테이너**: `flex min-w-0 flex-col gap-3 break-keep wrap-break-word text-sm leading-relaxed text-foreground`. 블록(문단·인용·코드·목록·구분선) 사이는 `gap-3`(12px)이다.

### 허용 요소
파서 단계에서 이 밖의 구문을 끄고(`remarkChatSubset`), 렌더 단계에서 `allowedElements`로 한 번 더 거른다.

| 요소 | 원문 | 렌더 |
|---|---|---|
| `p` | 빈 줄로 나뉜 글 | `m-0`, 블록 간격 `gap-3` |
| `br` | 문단 안 한 줄 바꿈(줄 끝 `\`·공백 두 칸도 같다) | 줄바꿈 |
| `em` | `*…*` | 지문 — `not-italic text-muted-foreground` |
| `strong` | `**…**` | `font-semibold` |
| `blockquote` | 줄 머리 `> `(`>` 뒤가 공백이거나 줄 끝) | 장면 헤더 — 아래 인용 |
| `pre` / `code` | ```` ``` ```` 또는 `~~~` 펜스 | 코드 블록 — 아래 코드 블록 |
| `code`(인라인) | `` `…` `` | `rounded-sm bg-foreground/10 px-1 py-0.5`, 고정폭 아님 |
| `hr` | 단독 줄 `---`·`***` | `m-0 h-px border-0 bg-border` |
| `ul` / `ol` / `li` | 줄 머리 `- `·`* `·`+ ` / `1. `·`1) ` | `list-disc`·`list-decimal pl-5 marker:text-muted-foreground`. `3. …`로 시작하면 3부터 센다 |

**렌더하지 않는 것 — 원문 글자가 그대로 남는다.** 요소만 걸러 내면 링크 주소·`#`·HTML 안쪽 글자까지 사라지므로 파서에서 구문 자체를 끈다.
- 제목(`# 제목`, `텍스트↵===`), 링크(`[링크](https://x.com)`), 이미지(`![img](a.png)`), 자동 링크(`<https://x.com>`), 링크 정의, HTML(`<b>굵게</b>`), 들여쓰기 코드(앞 공백만 지워진 문단이 된다). `텍스트↵---`는 제목이 아니라 문단 + 구분선이다.
- **GFM을 쓰지 않는다** — 표(`| a | b |`)는 글자 그대로다. 이유는 한국어 채팅의 물결표다: `반가워~ 또 봐~`처럼 `~`를 흔히 두 번 쓰는데, GFM 취소선은 그 사이를 통째로 그어 버린다. 그래서 `~~취소~~`도 글자다.
- **`_` 강조는 없다** — `>_<`·`^_^`·`ㅠ_ㅠ`·`file_name_here`를 깨뜨리므로 밑줄로 시작한 강조를 파서가 만들면 표지를 글자로 되돌린다(`remarkRevertUnderscoreEmphasis`, 안쪽의 `*` 지문은 산다).
- **날짜형 번호는 목록이 아니다** — `2026. 9. 29. 오늘`·`9. 29. 저녁`은 문단이다(`N. N.` 모양이면 첫 마침표를 이스케이프). `3. 규칙은 이렇다`는 목록이다. 인용·목록 표지 뒤에서도 같은 판정을 한다(`> 2026. 9. 29. | 23:40 | 옥상`).
- **줄 머리 `>` 뒤에 공백이 없으면 인용이 아니다** — `>_< 싫어`는 글자다.

### 파서 보정
- **한국어 flanking 재짝짓기** — CommonMark는 별표 양옆의 글자·구두점으로 여닫음을 정하는데(flanking), 한국어는 글자와 구두점(`"`·`.`·`~`·`…`)이 별표에 바로 붙어 `그녀가 웃었다*"안녕"*`·`*웃는다.*안녕` 같은 흔한 모양이 강조가 되지 못한다. 파서가 글자로 남긴 별표를 **공백 조건만으로** 다시 짝짓는다(`pairStarRuns`): 여는 런은 "다음 글자가 공백이 아님", 닫는 런은 "앞 글자가 공백이 아님". 뒤에 공백이 오는 런(`별점 5* 줬다`)은 여는 표지가 될 수 없어 글자로 남는다. 같은 종류(1개 = 지문, 짝수 = 굵게, 3개 이상 홀수 = 굵은 지문)끼리 짝짓고, 없으면 가장 가까운 다른 종류에서 닫는다 — 더 긴 런에서 닫으면 남는 별표가 다음 강조를 연다(`**"왜?"***고개를 든다*` → 굵게 + 지문).
- **끝까지 안 닫힌 `*`·`**`는 문단 끝까지 감싼다.** 스트리밍 중 모양과 저장 후 모양이 같은 규칙에서 나온다 — `**정말 중요해` → `**정말 중요해*` → `**정말 중요해**`가 세 단계 모두 굵게이고, 닫는 별표가 반만 도착한 순간 지문으로 뒤집히는 깜빡임이 없다. 문단 끝의 닫는 런은 앞이 공백이어도 닫는다(`*웃는다 *`).
- **뒤에 아무것도 없는 별표는 지운다** — 보여 줄 이유가 없는 반쪽 표지다(`안녕 *`). **끝의 단독 `*` 줄도 지운다** — 그대로 두면 빈 목록 점이 되는데, 스트리밍 중 막 도착한 별표든 저장된 메시지든 같다. 열린 코드 펜스 안의 별표는 지우지 않는다.
- **줄 머리에 `>`가 없는 줄이 오면 인용이 끝난다** — 마크다운의 lazy continuation(표지 없는 다음 줄을 앞 인용 문단에 이어 붙이는 규칙)을 쓰지 않는다. 장면 헤더 바로 아랫줄의 본문이 인용 안으로 흡수되어 작고 흐린 글자가 되지 않게 하기 위해서다. 인용을 여러 줄로 이으려면 줄마다 `>`를 붙인다.
- **중첩 상한** — 사용자 입력 길이에 상한이 없어 병리적 입력에서도 방이 깨지면 안 된다(재귀가 입력 길이만큼 깊어지면 호출 스택이 넘친다). 인용·목록 표지는 8겹까지만 표지이고 그 뒤는 글자, 별표 강조는 8겹까지만 만들고 더 깊은 표지는 지운다(지문 안의 지문은 겉보기가 같다), 한 문단의 `*`·`_`가 500개를 넘으면 파서의 강조 처리를 건너뛰고 별표 짝짓기에만 맡긴다. 테스트는 짝 없는 여는 별표 2만 개·인용 2만 겹이 1초 안에 렌더되는지 본다.

### 원문 → 렌더 예시
`↵`는 줄바꿈이다. 전체 사례는 위 테스트 셋에 있다.

| 원문 | 렌더 |
|---|---|
| `*둘러본다* "누구 있어요?"` | 지문 `둘러본다` + 대사 `"누구 있어요?"` |
| `*조심스럽게 주위를 둘러본다* "누구 있어요?" (조금 무섭다)` | 지문 + 대사, 괄호도 대사 색 글자 |
| `그녀가 웃었다*"안녕"*` | 대사 `그녀가 웃었다` + 지문 `"안녕"`(재짝짓기) |
| `*웃는다.*안녕` | 지문 `웃는다.` + 대사 `안녕`(재짝짓기) |
| `*계단을 내려온다` | 문단 끝까지 지문 |
| `**굵게*` → `**굵게**` | 두 순간 모두 굵게 |
| `**"왜?"***고개를 든다*` | 굵게 `"왜?"` + 지문 `고개를 든다` |
| `*그가 **"안 돼"**라고 했다*` | 지문 안에 굵게 |
| `****"굵게"****라고` | 굵게 `"굵게"` + 대사 `라고`(재짝짓기, 네 개 런은 굵게) |
| `별점 5* 줬다` | 글자 그대로 |
| `\*별표\*` | `*별표*` |
| `> D+0 \| 13:00 \| 장소` | 장면 헤더 인용 |
| `> D+1 \| 00:10 \| 계단`↵`*계단을 오른다* "잠깐만"` | 인용 한 줄 + 별도 문단(지문 + 대사) — 아랫줄은 인용에 흡수되지 않는다 |
| `2026. 9. 29. 오늘` | 문단(목록 아님) |
| `>_< 싫어` · `^_^ 좋아 ^_^` | 글자 그대로 |
| `# 제목` · `[링크](https://x.com)` · `<b>굵게</b>` | 글자 그대로 |
| `반가워~ 또 봐~` · `~~취소~~` | 글자 그대로(GFM 없음) |
| 펜스(```` ``` ````) 두 줄 사이의 `상태 *값*` | 코드 블록, 별표도 글자 그대로 |

### 레이아웃
- **유저와 캐릭터가 같은 컬럼에 흐르는 소설형이다.** 둘 다 상자 없는 산문이고 같은 렌더러로 그린다(좌우 정렬 분기 없음). 본문 폭은 `max-w-3xl`(768px)이고 `flex-1`을 주지 않는다 — 짧은 메시지는 내용 폭만큼만 차지해 `⋯` 메뉴가 글 끝 옆에 붙고, 메뉴는 `items-start`로 첫 줄 옆에 고정된다. 이 캡의 근거(줄 길이)는 Typography 절의 Body.
- **유저 메시지는 `border-l border-primary pl-3` — 1px `primary` 좌측선 + 12px 들여쓰기, 배경 없음.** "지금 내가 한 말"을 채움 없이 가른다. 수정 폼도 같은 틀이라 입력란이 원래 메시지 자리에서 열린다. 선이 1px인 이유는 1px를 넘는 유색 사이드 선이 카드·알림의 장식 스트라이프로 읽히기 때문이다(Do's and Don'ts 절의 사이드 보더 금지와의 관계 참고). 선 대 `background`는 다크 7.18 / 라이트 6.70:1로 비텍스트 3:1을 넘는다(Colors 절의 Primary와 같은 8비트 공표값).
- **메시지 사이는 `gap-6`(24px) — 한 메시지 안 문단 간격(`gap-3`, 12px)의 두 배다.** 상자가 없는 산문이 한 컬럼에 흐르므로 두 값이 같으면 "여기서 다른 사람의 말이 시작된다"와 "같은 사람이 문단을 바꿨다"가 구분되지 않는다.
- 판정 이미지(상황별 이미지·미디어 북 그림)는 본문 아래 `self-start` 블록으로 붙는다. 서버가 캐릭터 응답에만 붙이지만 역할로 가르지 않고 이미지가 있으면 그린다. 크기를 모르는 그림은 고정 3:4 웰(`aspect-3/4 h-80 max-w-3/4 rounded-lg bg-muted`), 크기를 아는 그림은 원본 비율 틀이다(Components 절의 Media images).
- 첫 메시지·에필로그 글 속 미디어 북 태그 자리에는 같은 틀의 그림이 **문단 밖 블록**으로 선다 — 태그가 문단 한가운데나 지문 안에 있어도 문단(지문)을 둘로 쪼개 그림을 그 사이 블록으로 올린다. 그림 맵이 없는 자리(사용자 메시지·스트리밍 중 응답·그 밖의 대화)에서는 태그를 그림으로 바꾸지 않는다.

### 인용(장면 헤더)
- 용도는 `> D+0 | 13:00 | 장소` 같은 장면 헤더다. **`text-xs text-muted-foreground`**(본문보다 한 단계 작고 흐리다) + **무채 1px 선**(`border-l border-border pl-3`), 안쪽 문단 사이 `gap-1`.
- **이 선은 장식이라 대비 요건이 없다고 판단했다.** `border` 대 `background`는 다크 1.43 / 라이트 1.38:1(Colors 절 Neutral의 8비트 공표값 1.4312 / 1.3845)로 3:1에 못 미치지만, 인용임을 알리는 신호는 선이 아니라 작고 흐린 글자와 들여쓰기가 함께 지고, 선이 안 보여도 잃는 정보가 없다. `border`가 장식 구분선에 쓰이는 규범(Colors 절의 Neutral)과 같다. 유저 메시지 선과 색으로 갈리는 것도 의도다 — `primary` 선은 "내가 한 말", 무채 선은 장면 정보다.
- `hr`은 같은 `bg-border` 1px 선이다. 엔딩 구분선(`EndingDivider`)도 1px `bg-border` 선이지만 가운데 엔딩 이름을 담은 알약 배지(`rounded-full bg-secondary`)가 있어 모양으로 갈린다.

### 코드 블록
- 상태창처럼 칸을 맞춘 글을 위한 자리다. `<pre>`에 **`font-mono text-xs leading-relaxed`**, `whitespace-pre-wrap`(가로 스크롤 대신 줄을 접는다 — 좁은 화면에서 옆으로 밀어 읽게 할 이유가 없고, `overflow-x-auto`는 복사 버튼의 포커스 링까지 잘라 낸다), `rounded-lg py-3 pr-11 pl-3`. 글자 색은 컨테이너의 `foreground`를 물려받는다. 언어 태그(```` ```info ````)는 버리고 원문 글자만 그린다.
- **고정폭 스택은 `--font-mono`(`globals.css`) 하나다**: `ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace, "Pretendard Variable"`. 웹폰트를 더 받지 않고 기기의 고정폭 서체를 쓴다. **순서가 곧 규칙이다** — 브라우저는 글자마다 이 목록을 앞에서부터 훑어 그 글자를 가진 첫 서체를 고른다. 이름 붙은 서체가 하나도 없는 기기(안드로이드·리눅스)에서도 라틴 글자가 비례폭 Pretendard로 새지 않도록 generic `monospace`를 Pretendard 앞에 두고, 고정폭 서체에 대개 없는 한글은 그다음 Pretendard가 잡는다. 그래서 한글이 라틴 칸에 맞춰 정렬된다는 보장은 없다 — 칸 맞춤이 온전한 것은 라틴·숫자·기호뿐이다.
- **면 색**: 기본 `bg-muted`(`background` 위 다크 1.0946 / 라이트 1.0902:1 — Colors 절의 "표면 위 채움 규칙"과 같은 8비트 공표값). **Dialog·card 위에서는 `bg-secondary`**(`codeBlockSurface="secondary"`, 지금은 엔딩 컬렉션 모달) — `muted`는 `card`·`popover`와 같은 값이라 그 위에서 1.0000:1로 사라진다(Colors 절의 "표면 위 채움 규칙"). `secondary`면 위에서도 코드 글자는 `foreground`로 둔다 — **`secondary` 위 `muted-foreground`는 라이트 4.30:1로 AA 미달이라 글자에 쓰지 않는다.**
- **복사 버튼**: 우상단 `absolute top-1.5 right-1.5`, `Button variant="ghost" size="icon-sm"`, `aria-label="코드 복사"`, 아이콘은 `aria-hidden`. 글리프는 `text-muted-foreground`다 — 비텍스트라 기준이 3:1이고 가장 낮은 `secondary` 면 위 라이트 4.30:1도 넘는다. hover는 `hover:bg-foreground/10`으로 덮는다 — ghost 기본 hover(`bg-muted`)는 `muted` 코드 면과 같은 값이라 사라지기 때문이다(반투명 전경색은 어느 면 위에서도 보인다). 피드백은 토스트이고 모션은 새로 더하지 않는다(Motion 절).
- 인라인 코드는 고정폭을 쓰지 않는다 — 문장 속 짧은 구간이라 Pretendard 그대로 두고 `bg-foreground/10` 틴트로만 구간을 표시한다(반투명 전경색이라 어느 면 위에서도 사라지지 않는다).

### 대비
채팅 영역에는 따로 칠한 면이 없어 배경은 `background`다. **같은 조합은 다른 절이 이미 공표한 값을 그대로 쓴다** — 글자 쌍(대사·지문)은 Colors 절 Neutral 목록의 값(부동소수 sRGB 변환), 선(`primary`·`border`)은 Colors 절 Primary·Neutral의 8비트 공표값이다. 지문 대 대사는 다른 절에 없는 조합이라 글자 쌍과 같은 부동소수 계산으로 적었다(8비트로는 다크 2.35 / 라이트 3.28).

| 조합 | 다크 | 라이트 |
|---|---|---|
| 대사 `foreground` / `background` | 15.79 | 17.31 |
| 지문 `muted-foreground` / `background` | 6.74 | 5.28 |
| 지문 대 대사 (`muted-foreground` / `foreground`) | 2.34 | 3.28 |
| 유저 선 `primary` / `background` | 7.18 | 6.70 |
| 인용 선 `border` / `background` | 1.43 | 1.38 |

- **지문 대 대사는 참고치다.** 둘 다 배경 대비 AA를 넘으므로 읽기는 문제가 없지만, **둘을 가르는 신호가 명도 하나뿐이다** — 별표는 지워지고 이탤릭도 없다. 다크에서 2.34:1은 가깝게 붙은 두 명도라, 명도 차를 잘 못 느끼는 사용자나 화면 밝기를 크게 낮춘 환경에서는 지문과 대사가 같은 글자로 읽힐 수 있다. 따옴표로 대사를 적는 관습이 보조 단서가 되지만 렌더러가 보장하는 것은 아니다.

### 목록 미리보기
대화 목록(`ChatRoomListItemRow`·`MyChatRoomListView`)의 마지막 메시지 한 줄은 `stripChatNotation`으로 표기 기호를 지운 평문이다 — 지문·굵게 별표, 인용 `> `, 목록 표지, 구분선, 코드 펜스 줄을 지우고, 코드 안 글자와 렌더하지 않는 구문(`# 제목`, 링크, HTML)은 그대로 둔다. 별표는 본문과 **같은 짝짓기 규칙**(`chatNotationSyntax.ts`)으로 문단 단위로 짝짓고, 결과는 한 칸 띄움으로 이은 한 줄이다. 테스트가 미리보기와 본문이 화면에 남기는 글자가 같은지 사례마다 대조한다. 색 구분은 없다(`truncate text-xs text-muted-foreground`).

### 입력 보조
채팅방·빌더 미리보기 입력창 옆(전송 버튼 앞)에 **지문 표시 버튼**(`NarrationMarkerButton`, `Asterisk` 아이콘, `variant="ghost" size="icon"`, `text-muted-foreground`, `aria-label="지문 표시 넣기"`, 전송 중 비활성)이 있다. 메시지 수정 폼에는 없다. 동작은 `insertNarrationMarker`:
- **선택이 없으면** 별표 한 쌍(`**`)을 넣고 캐럿을 그 사이에 둔다.
- **선택이 있으면** 별표로 감싸고 캐럿을 닫는 별표 뒤로 옮긴다(선택을 남기면 이어 치는 글자가 감싼 글을 덮어쓴다). 양끝 공백은 별표 밖에 남긴다 — `* 끄덕였다*`처럼 별표가 공백에 붙으면 지문으로 읽히지 않는다.
- **이미 지문이면 벗긴다**(별표까지 골랐든 안쪽만 골랐든). 굵게(`**`)는 지문이 아니라 벗기지 않는다.
- **빈 줄을 넘는 선택은 문단마다 따로 감싼다** — 별표 짝이 문단 경계를 넘지 못하기 때문이다. 이미 지문인 문단은 그대로 두고, 전부 지문이면 전부 벗긴다.
- **IME**: 누르는 순간 `pointerdown`을 막아 입력창 포커스를 지킨다(모바일 키보드가 내려갔다 올라오지 않게). 단 한글 조합 중이면 막지 않는다 — 포커스가 빠지면서 브라우저가 조합을 먼저 확정하고, 클릭이 확정된 글(입력창의 실제 값)을 기준으로 별표를 넣은 뒤 다음 프레임에 포커스와 캐럿을 돌려준다. 조합 중에 값을 바꾸면 마지막 음절이 겹치거나 사라질 수 있다.

### 모델 출력 규칙
캐릭터가 이 표기로 답하게 하는 지시는 공통 프롬프트에 있다. **그 문안은 코드가 아니라 DB에 있다** — 어드민의 프롬프트 세트(`/prompt-sets`)에서 고친다. 이 절의 원문 규칙을 바꾸면 그 문안도 함께 맞춘다. 시드 작품의 서술·행동 원문도 이 표기로 바뀌어 있다.

### 알려진 한계
- **`2*3=6 이고 4*5=20`은 지문으로 읽힌다** — 글자 사이 별표는 공백 조건을 만족해 짝지어진다. 한국어 재짝짓기의 대가로 받아들였다. 수식은 `\*` 또는 코드로 적는다.
- **줄 머리 `* "대사"`는 목록 점이 된다** — 줄 머리 `* ` 뒤 공백은 CommonMark 목록 표지다. 지문을 그 모양으로 시작하려면 별표를 글자에 붙인다(`*"대사"*`).
- **유저 메시지 안에 인용이 있으면 선 두 개가 나란히 선다** — 1px `primary` 좌측선과 인용의 1px 무채 선이 13px 간격(두 선의 왼쪽 끝 사이 — 유저 선 1px + 유저 틀 `pl-3` 12px)으로 나란히 보인다. 유저가 장면 헤더를 쓰는 일은 드물어 받아들였다.
- **문단 끝에 공백 없이 붙은 별표는 반쪽 표지로 지워진다** — `별점 5*`로 끝나는 문단은 `별점 5`가 된다(뒤에 공백이 있으면 남는다).

## 7. Do's and Don'ts

### Do:
- **Do** 색을 쓰고 싶으면 그것이 강조 지점(`primary`/`ring`)인지, 사용자 콘텐츠인지, 위험 액션인지 먼저 확인한다. 셋 다 아니면 무채색이다.
- **Do** 새 표면을 Colors 절의 명도 사다리 위에 올린다(다크 0.160/0.210/0.260/0.300). 사다리에 없는 중간값을 발명하지 않는다.
- **Do** 깊이를 그림자가 아니라 명도로 만든다. 카드가 떠 보여야 하면 `bg-card`를 쓰지 `shadow-md`를 쓰지 않는다.
- **Do** 다크에서 채움 위 텍스트를 뒤집는다 — `primary`와 `destructive` 모두 밝은 채움 + 어두운 텍스트다. 이 쌍을 깨지 말 것.
- **Do** 애니메이션에 `motion-safe:`를 붙인다 — 예외는 Motion 절에만 적는다.
- **Do** 모든 인터랙티브 엘리먼트에 `focus-visible` 표시를 유지한다 — 50% 링(`ring-3 ring-ring/50`)에 불투명 1px(보더가 있으면 `border-ring`, 없으면 `outline-1 outline-ring`)을 함께 둔다. 50% 링만으로는 배경 대비 3:1에 못 미친다(Buttons 절의 Focus, 전연령/접근성 정책). 예외는 다이얼로그의 스크롤 본문(`DialogBody`에 `scrollLabel`을 준 Tab 정지) 하나로, 바깥 링 대신 안쪽 2px `outline-ring`을 그린다 — 다이얼로그 전폭인 이 상자의 바깥 링은 다이얼로그 밖 스크림 위에 그려지고, 안쪽 그림자 링은 스크롤하는 내용에 덮이기 때문이다.
- **Do** 본문에 `text-sm`(1rem)을 쓴다. 이것이 기본값이다.

### Don't:
- **Don't** 다크에서 순백(`oklch(1)`, `text-white`, `#fff`)을 쓰지 않는다. 천장은 `foreground`(0.930)다.
- **Don't** 자극적이거나 성인 지향적인 비주얼 톤을 쓰지 않는다(전연령 정책) — 원색 대비, 네온, 선정적 이미지 트리트먼트.
- **Don't** `primary`를 배경 전체 채우기나 텍스트 그라디언트로 쓰지 않는다. `primary`는 "지금 누를 수 있는 것"과 "지금 내가 한 말"(채팅 사용자 메시지의 1px 좌측선 — 채움이 아니다)에만 쓴다.
- **Don't** 솔리드 레드 버튼/배지를 만들지 않는다. destructive는 언제나 틴트다(알파는 Colors 절의 목록).
- **Don't** 카드·버튼·인풋에 정지 상태 그림자를 붙이지 않는다.
- **Don't** Toast/Alert에 색상 사이드 보더를 쓰지 않는다. 상태는 아이콘 색과 텍스트로만 구분한다. **채팅 사용자 메시지의 1px `primary` 좌측선은 이 금지의 대상이 아니다** — 상태를 알리는 장식이 아니라 상자 없는 한 컬럼에서 "내가 한 말"을 가르는 유일한 표시이고, 상자·배경 없이 1px로 제한된다. 이것을 근거로 다른 자리에 유색 사이드 선을 더하지 말 것(Chat Notation 절의 레이아웃).
- **Don't** 서로 다른 서체 패밀리를 섞지 않는다 — Pretendard 굵기 변화로만 위계를 만든다. 예외는 채팅 코드 블록의 기기 고정폭(`--font-mono`) 하나다(Typography 절의 단일 서체 규칙).
- **Don't** clamp()나 vw 유동 타이포를 쓰지 않는다. 모든 크기는 고정 rem이고 천장은 `text-2xl`이다. web에서 예외는 `/about` 태그라인 한 줄의 `text-4xl`, 그리고 소설 화 읽기 화면 페이지 모드의 판형 안(px 고정 + 배율 0.8~1.2)뿐이며 다른 화면으로 번지지 않는다(Typography 절의 히어로 없음 규칙).
- **Don't** 크롬의 자리를 새로 만들지 않는다 — 상시 크롬은 위쪽 `h-14` 헤더 한 줄과 `lg` 이상의 좌측 패널 한 열뿐이고, 하단 탭바·두 번째 가로 줄·오른쪽 레일·sticky/fixed 푸터·두 번째 푸터는 추가하지 않는다. 한 화면에만 두는 것이라도 정지 상태에 늘 자리를 차지하는 sticky/fixed 띠를 헤더 자리 밖에 더하지 않는다(기록된 예외는 상세화면 하단 플레이 바 — Navigation 절). 새 목적지는 헤더나 패널(`lg` 미만은 드로어)에 넣는다. 허용되는 것은 문서 끝의 정보 푸터 하나다(Navigation 절). `<main>` 내부에서 콘텐츠를 여러 열로 나누는 것은 대상이 아니다(판별 기준 Navigation 절). 소설 화 읽기 화면만은 전역 헤더·푸터 대신 탭으로 부르는 위·아래 바를 쓰고(페이지 모드에서는 그 자리를 늘 비워 둔다), 페이지 모드의 마우스·트랙패드 기기에서는 본문 밖 여백에 넘김 버튼 둘을 늘 둔다 — 정지 상태에 크롬 줄이 하나도 없는 그 라우트만의 예외이고 다른 화면으로 번지지 않는다(Navigation 절). 이 Don't는 `apps/web` 규칙이다 — `apps/admin`의 사이드바와 상세 조치 바는 Navigation 절.
- **Don't** 라이트 테마에서 `accent`(0.930) 표면 위에 `muted-foreground`로 본문을 올리지 않는다 — 4.30:1로 AA 미달이다.
- **Don't** `space-y-*`나 `divide-*`를 쓰지 않는다. 간격은 `flex flex-col gap-*`으로만 만든다.
