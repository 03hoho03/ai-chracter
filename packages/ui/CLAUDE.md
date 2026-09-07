# packages/ui

shadcn 기반 공용 프리미티브 + 디자인 토큰. web·admin이 함께 쓴다.

**이 문서는 구현 배선만 담는다.** 무엇이 어떻게 보여야 하는가(색·대비 수치·포커스 레시피·모션 정책)는 `DESIGN.md`, 토큰 값의 유일한 소스는 `src/styles/globals.css`다 — **여기에 토큰 값을 다시 적지 않는다.**

## 작업 라우팅 — "무슨 작업 → 어디"

| 작업 | 위치 / 패턴 |
|---|---|
| shadcn 컴포넌트 추가 | `npx shadcn@latest add <name> -c packages/ui` → 아래 §정리 관례대로 손본다 |
| 토큰 추가·변경 | `globals.css`의 `:root`/`.dark`/`@theme inline` **한 곳**. 근거는 `DESIGN.md`에 남긴다 |
| 새 앱을 이 패키지에 붙이기 | `@tailwindcss/vite` 플러그인 + 진입점에서 `@ai-character-chat/ui/globals.css` import + `@source` 확인 |
| 컴포넌트 대비·모션 규칙 | 프리미티브에서 고친다(호출부 처방이 안 통하는 이유는 §프리미티브에서만) |
| 폭·높이·줄바꿈 | 대개 호출부 처방이다(§호출부에서) |
| 토스트 | `sonner` 직접 import. 쓰는 앱은 자기 `package.json`에 의존성 추가 필수 |

## 빌드 / 토큰 배선

- **Tailwind v4(CSS-first)라 `tailwind.config.js`가 없다.** 색·타이포·spacing·radius 토큰은 전부 `globals.css` 한 파일에 있다.
- **`@source` 경로는 CSS 파일 위치(`src/styles/`) 기준 상대경로다.** 새 앱을 추가할 때 그 앱의 `src`가 기존 글롭(`../../../../apps/**/*.{ts,tsx}`)에 걸리는지 확인하고, 안 걸리면 줄을 추가한다 — 안 하면 그 앱에서만 클래스가 조용히 안 나온다.
- **다크는 `.dark` 클래스 기반이다**(`@custom-variant dark (&:is(.dark *))`). `html`에 클래스를 붙이면 전환되고, `:root`/`.dark` 양쪽에 `color-scheme`이 선언돼 네이티브 컨트롤·스크롤바도 따라온다. **admin은 `.dark`를 절대 붙이지 않아 라이트 값만 적용된다** — 이 패키지를 고칠 때 다크만 확인하고 끝내지 말 것.
- **`data-open:`·`data-active:`·`data-horizontal:` 같은 축약 variant는 Tailwind 내장이 아니다** — `globals.css`의 `@import "shadcn/tailwind.css"`가 정의한다. 순수 tailwindcss로 컴파일하면 `&[data-active]`(불리언 매칭)로 나와 죽은 셀렉터처럼 보이지만 실제 앱에서는 동작한다 — **"안 맞는 셀렉터"로 오판해 고치지 말 것.** shadcn이 정의하지 않은 상태(`data-state=inactive` 등)는 명시 문법 `data-[state=inactive]:`를 쓴다.
- 폰트는 Pretendard variable **dynamic-subset**을 `globals.css`에서 직접 import한다(`pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css`). Fontsource 계열이 아니다.

## shadcn 컴포넌트 정리 관례

CLI가 뱉은 소스를 그대로 두지 않는다. 새로 추가할 때도 같이 한다:

- **`dark:` variant 클래스는 제거한다** — 토큰 기반이라 대부분 `.dark` 블록만으로 동작한다. 다크에서 토큰만으로 대비가 안 나오는 경우에만 선별 복원한다.
- 사용자 노출 텍스트("Close" 등)는 한국어로 교체한다.
- **상류 기본값이 이 시스템과 충돌하는 자리가 있다** — 예: `toggle`의 선택 상태 `bg-muted`, 메뉴 비활성 항목 `opacity-50`. `shadcn add`로 재생성하면 되돌아오므로 재생성 후에는 `DESIGN.md` §5의 해당 컴포넌트 항목과 대조할 것.
- Toast는 deprecated된 `toast`가 아니라 **`sonner`**다. `<Toaster />`는 앱 루트에 한 번만 마운트하고 호출은 각 기능 코드에서 `import { toast } from "sonner"` — 패키지가 재노출하지 않으므로 **쓰는 앱의 `package.json`에 `sonner`를 직접 넣어야 한다**(pnpm 워크스페이스는 간접 의존성을 안 끌어온다). `Toaster`의 `theme` prop 기본값은 `"light"`라 web은 `AppToaster`가 현재 테마를 넘기고, admin은 라이트 고정이라 넘기지 않는다.

## 호출부에서 처방하는 것 (프리미티브를 고치면 안 되는 자리)

- **`DropdownMenuContent`의 폭은 트리거 폭에 고정돼 있다**(`w-(--radix-dropdown-menu-trigger-width)` + `min-w-32`, `w-`는 이 저장소가 더한 것). 그래서 **아이콘 버튼(32px)이 트리거면 메뉴가 128px에 갇혀** 라벨이 두 줄로 깨진다 — 그 호출부에 `className="w-auto"`를 얹는다. 프리미티브를 고치면 헤더 프로필·알림 등 기존 메뉴 폭이 함께 바뀐다.
- **`DialogContent`에는 최대 높이도 내부 스크롤도 없다.** 내용이 길어질 수 있는 다이얼로그는 호출부에서 `max-h-[calc(100dvh-2rem)] overflow-y-auto`를 얹을 것 — Radix가 body 스크롤을 잠그므로 빼먹으면 **화면 밖으로 밀린 푸터에 닿을 방법이 없다**.
- **`DialogDescription`에 `break-keep`이 없다.** 한국어 본문이 어절 중간에서 끊기는데 **넓은 폭에서만 나타나는 게 함정이다**(좁은 화면은 우연히 문장 경계로 접힌다). 지금은 한국어 본문 7곳 전부 호출부에서 `className="break-keep"`을 준다.
- **`Button`의 `size="lg"`를 단독으로 쓰지 않는다.** `default`와 패딩·타이포가 같고 높이만 32→36px이라, 같은 라벨의 두 버튼에 걸면 폭이 완전히 같아져 위계가 아니라 **정렬 오차로 읽힌다**. 호출부는 전부 `h-10`(폼 제출)·`h-12`(플레이)로 덮어쓴다 — **실제 출하 어휘는 32/40/48px이고 36px 티어는 없다.** 크기로 위계를 만들려면 오버라이드까지 함께 쓰고, 아니면 라벨·배치로 가른다.

## 프리미티브에서만 고칠 수 있는 것

호출부 처방이 **원리적으로 불가능한** 자리다. 같은 모양의 컴포넌트를 새로 만들 때 함께 넣어야 한다.

- **모션 게이팅** — `motion-reduce:animate-none`을 호출부에서 얹어도 `data-open:` 변형의 속성 선택자가 특이도에서 이긴다. 새 프리미티브에는 `animate-*`/`transition-*`뿐 아니라 **`duration-*`까지** `motion-safe:`로 감싼다(정책과 예외는 `DESIGN.md` §5 Motion).
- **`outline-hidden`을 쓴 옵션 리스트의 포커스 링** — 그 유틸리티가 UA 아웃라인을 지우므로 링을 함께 넣지 않으면 남는 신호가 배경 변화뿐이다. 적용 대상과 수치는 `DESIGN.md` §5 Menus. `inset-ring-*`는 v4 유틸리티이고, item base에 `ring-*` 키가 없어 `cn()`으로 충돌 없이 얹힌다.
- **사유를 읽혀야 하는 비활성 항목은 `disabled`가 아니라 `aria-disabled`로 만든다.** Radix의 `disabled`는 `RovingFocusGroup.Item`의 `focusable: !disabled`로 항목을 **포커스 순회와 타입어헤드에서 통째로 뺀다** — "왜 못 누르는지"가 키보드·스크린리더에 영원히 닿지 않는다. `aria-disabled` + `onSelect`의 `preventDefault`면 순회에 남고 눌러도 안 열리며 메뉴가 안 닫혀 사유가 그 자리에 남는다. 그래서 item 클래스에 `aria-disabled:opacity-65`가 `data-disabled:opacity-65`와 **같은 값으로 함께** 걸려 있다.
- **확인 모달의 버튼 순서는 언제나 `취소` 먼저, 실행 나중이다 — DOM·시각·탭 셋이 같다.** `DialogFooter`/`AlertDialogFooter`가 `sm` 미만에서 상류의 `flex-col-reverse`가 아니라 **`flex-col`**이고, `DialogContent`의 닫기(X)가 `{children}` **앞**에 렌더된다. **"확인 버튼이 위"는 취향이 아니라 DOM 순서가 배제하는 배치다** — DOM 순서는 반응형이 될 수 없는데 `sm` 이상의 `취소 왼쪽 · 실행 오른쪽`을 유지하려면 DOM이 `[취소, 실행]`이어야 하고, 그러면 좁은 화면 세로 배치는 `취소` 위로 정해진다. 되돌리려면 `sm` 이상까지 함께 뒤집어야 한다. 호출부의 `autoFocus`는 그대로 이긴다(Radix FocusScope가 이미 컨테이너 안에 포커스가 있으면 자기 로직을 건너뛴다).
- **`AlertDialogContent`의 폭은 `w-[calc(100%-2rem)]`이지 `max-w-*`가 아니다.** `max-w-xs`를 물고 있는 쪽이 `data-[size=…]:` 변형이라 특이도 (0,2,0)으로 평평한 `max-w-[…]`(0,1,0)을 언제나 이겨, 320px 뷰포트에서 **좌우 여백이 0**이 됐다. `DialogContent`가 `max-w-`로 같은 여백을 얻는 건 거기엔 경쟁하는 `data-*` 변형이 없어서다.
- **긴 메뉴가 잘릴 때의 하단 페이드**(`data-clipped-below`) — macOS·iOS 오버레이 스크롤바에는 상시 표시가 없어 **잘렸다는 신호가 하나도 없다**(메뉴가 구분선에서 끊기면 완결된 메뉴처럼 보인다). 콜백 ref가 `scrollHeight - scrollTop - clientHeight > 1`을 재서 속성을 세우고, 그때만 `::after` 스티키 그라디언트(`h-8`, `from-popover`)가 얹힌다. **높이 32px은 대비가 정한 값이라 임의로 못 늘린다**(40px이면 글리프가 라이트에서 AA 미달 — 다크만 재면 못 잡는다). 안 넘치는 메뉴는 `::after`가 아예 생성되지 않는다. **새 메뉴는 항목 수를 세지 말고 가로 폰 높이(available-height 342px)에 재 볼 것.** `SelectContent`는 Radix의 스크롤 버튼이 신호를 져서 해당 없고, 손으로 만든 `ShortcutAutocomplete`는 아직 신호가 없다(미측정).

## 토큰을 건드릴 때

값과 근거는 `globals.css`·`DESIGN.md`에 있고, 여기엔 **측정 방법**만 둔다.

- **정지 상태 대비만 재면 부족하다.** `button`의 default variant는 hover에서 `bg-primary/80`이라 채움이 배경 쪽으로 옅어지고(v4가 `color-mix(in oklab, …)`로 컴파일한다), 정지에서 통과하던 조합이 hover에서 AA 아래로 떨어진다. **hover 값까지 함께 재고 고를 것.**
- 브라우저에서 재는 법: 1×1 canvas에 배경을 칠하고 그 위에 `color-mix(in oklab, <token> 80%, transparent)`를 덧칠해 `getImageData`로 읽는다. **`getComputedStyle`로 `oklch()` 문자열을 rgb로 파싱하면 조용히 1.00이 나온다** — 반드시 canvas로 변환할 것.
- **포커스 대비는 전이가 정착한 뒤 재야 한다** — `transition-all` 0.15s가 box-shadow까지 애니메이션해서 Tab 직후 읽으면 전이 중간값이 잡힌다.
- **chroma는 취향이 아니라 sRGB 게멋 상한에 걸린다.** 상한을 넘긴 값을 적으면 브라우저가 조용히 클리핑해 의도한 색이 안 나온다 — oklch→linear sRGB로 변환해 세 채널이 0~1 안인지 먼저 확인한다.
- **유채색 토큰은 `*-foreground`와 쌍으로 움직인다**(다크에서 밝힌 채움 위 흰 텍스트가 AA 미달이라 뒤집어 둔 것). 한쪽만 조정하지 말 것 — 자세한 근거는 `DESIGN.md` §2 Semantic.

## 알려진 갭

- **문장 속 인라인 링크는 쉬는 상태에서 링크로 안 읽힌다.** 저장소 관용구 `font-medium text-primary hover:underline`은 배경 대비는 넉넉하지만 **링크 텍스트 대 주변 본문 대비가 1.07 다크 / 1.28 라이트**라, 색을 링크 식별자로 쓸 때 WCAG G183이 요구하는 3:1에 한참 못 미친다(다크에서는 사실상 *같은 밝기의 다른 hue*라 적록색약 사용자에게 구별되지 않는다). 정지 상태의 비색 단서는 `font-medium` 한 단계뿐이다. 처방은 `underline underline-offset-4`(후자는 `button.tsx`의 `link` variant가 이미 쓰는 값이라 새 어휘가 아니다)이고, **한 곳만 붙이면 시각 언어가 갈리므로 web 5파일·admin 2파일 10곳을 함께 옮기는 일괄 항목이다.** hover·focus에는 이미 밑줄이 그려진다.
