import { describe, expect, it } from "vitest";

/**
 * `card`/`popover` 표면 위에서는 `bg-muted`를 쓰지 않는다(DESIGN.md §Colors "표면 위 채움" 규칙).
 *
 * 세 토큰 `card`·`popover`·`muted`는 같은 값이다(다크 0.21 / 라이트 0.97). 그래서 모달·카드 위에
 * 깐 `bg-muted` 스켈레톤·웰·hover·선택 채움은 표면 대비 **1.0000:1로 사라진다**.
 * 그 자리의 채움은 `secondary`다. `muted`는 `background` 위 첫 레이어(스켈레톤·웰) 전용이다.
 *
 * 규칙(파일 단위 휴리스틱): 주석을 걷어 낸 소스에 **표면 표식**(`DialogContent` 등 popover 표면을
 * 여는 컴포넌트, 또는 `bg-card`/`bg-popover` 클래스)이 있으면, 그 파일의 `bg-muted` 클래스 토큰
 * (`hover:`·`aria-selected:` 같은 변형 접두와 `/50` 알파 포함, `bg-muted-foreground`는 제외)은 실패다.
 * 예외는 아래 `ALLOWLIST`에 이유와 **기대 토큰 목록**과 함께만 둔다 — 파일을 통째로 면제하지 않는다.
 *
 * 한계: 모달 본문을 **다른 파일의 컴포넌트**로 뺀 경우는 못 잡는다(표식과 채움이 다른 파일에 있다).
 * 할 일: 재발하면 컴포넌트 트리 기반 검사를 검토한다.
 * admin(`apps/admin`)은 형제 앱이라 스캔하지 않는다(admin에 vitest가 없다).
 *
 * 소스를 문자열로 읽는 이유는 `searchSchemaContract.test.ts`와 같다(node 환경에서 컴포넌트를 import하면
 * 모듈 최상위 `localStorage` 접근에서 죽는다).
 */
const WEB_SOURCES = import.meta.glob<string>("../../../**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** web이 의존하는 공용 프리미티브 — `DialogFooter`처럼 표면과 채움이 같은 파일에 있는 자리. */
const UI_SOURCES = import.meta.glob<string>("../../../../../../packages/ui/src/components/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

const ALL_SOURCES: Record<string, string> = { ...WEB_SOURCES, ...UI_SOURCES };

/**
 * 표면 표식이 있어도 `bg-muted`가 맞는 파일. 키는 glob 경로, `reason`은 **그 `bg-muted`가 어느 표면
 * 위에 있는지**, `tokens`는 그 파일에서 걸리는 토큰 전부(등장 순서)다. 실제 목록이 기대와 한 개라도
 * 다르면 실패한다 — 등재 파일에 `bg-muted`가 **새로** 들어와도(표면 위일 수 있다), 고쳐서 빠져도
 * (낡은 예외) 빨강이다. 새 토큰이 정말 background 위라면 `tokens`와 `reason`을 함께 고친다.
 */
const ALLOWLIST: Record<string, { reason: string; tokens: string[] }> = {
  "../../../entities/chat-room/ui/MessageBubble.tsx": {
    reason:
      "표식은 말풍선 ⋯ 메뉴의 DropdownMenuContent뿐이다. bg-muted 이미지 웰 둘은 그 메뉴 밖, 채팅방·미리보기 " +
      "화면(h-below-header 전체 페이지)의 background 위에 있다.",
    tokens: ["bg-muted", "bg-muted"],
  },
  "../../../features/submit-inquiry/ui/SubmitInquiryForm.tsx": {
    reason:
      "표식은 카테고리 Select의 SelectContent뿐이다. bg-muted 첨부 미리보기 웰은 InquiryNewPage의 <main> " +
      "(background) 위에 있다.",
    tokens: ["bg-muted"],
  },
  "../../../widgets/content-detail/ui/ContentDetailView.tsx": {
    reason:
      "SURFACE_FILL_CLASS가 variant로 채움을 가른다 — modal(DialogContent 위)은 bg-secondary, page(background " +
      "위)만 bg-muted다(그 상수의 page 값 하나). 표식은 modal 변형의 하단 바 bg-popover다.",
    tokens: ["bg-muted"],
  },
};

/** 표면 표식 — popover 표면을 여는 프리미티브 이름, 또는 표면 클래스 자체. */
const SURFACE_MARKER =
  /(?<![\w-])(?:DialogContent|AlertDialogContent|PopoverContent|SheetContent|DropdownMenuContent|DropdownMenuSubContent|SelectContent|bg-card|bg-popover)(?![\w-])/;

/** `bg-muted` 클래스 토큰. 앞은 변형 접두의 `:`나 공백·따옴표, 뒤는 `/NN` 알파만 허용한다. */
const MUTED_FILL = /(?<![\w-])bg-muted(?:\/\d+)?(?![\w-])/g;

/**
 * 주석을 걷어 낸다(`// …`, `/* … *\/`, JSX `{/* … *\/}`). 문자열 리터럴 안은 건드리지 않는다 —
 * `accept="image/*"` 같은 값을 블록 주석 시작으로 오인하면 뒤의 코드가 통째로 사라져 **조용히 통과**한다.
 * 작은따옴표·큰따옴표 문자열은 줄바꿈에서 끊는다(JS 문자열은 여러 줄이 안 된다) — JSX 텍스트의
 * 아포스트로피가 문자열로 오인돼도 그 줄 안에서 복구된다.
 */
function stripComments(source: string): string {
  let out = "";
  let i = 0;
  let quote: string | undefined;

  while (i < source.length) {
    const char = source[i];
    const next = source[i + 1];

    if (quote !== undefined) {
      out += char;
      if (char === "\\") {
        out += next ?? "";
        i += 2;
        continue;
      }
      if (char === quote || (char === "\n" && quote !== "`")) quote = undefined;
      i += 1;
      continue;
    }

    if (char === "/" && next === "/") {
      while (i < source.length && source[i] !== "\n") i += 1;
      continue;
    }
    if (char === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);
      i = end === -1 ? source.length : end + 2;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") quote = char;
    out += char;
    i += 1;
  }

  return out;
}

function mutedTokensOnSurface(source: string): string[] {
  const code = stripComments(source);
  if (!SURFACE_MARKER.test(code)) return [];
  return code.match(MUTED_FILL) ?? [];
}

const OFFENDERS = Object.entries(ALL_SOURCES)
  .map(([path, source]) => ({ path, tokens: mutedTokensOnSurface(source) }))
  .filter(({ tokens }) => tokens.length > 0);

describe("card/popover 표면 위 bg-muted 금지", () => {
  it("검사 대상을 실제로 찾았다 — glob이 0건이면 아래 검사가 통째로 공회전한다", () => {
    expect(Object.keys(WEB_SOURCES).length).toBeGreaterThanOrEqual(150);
    // ui는 개수 대신 이 규칙의 표본 두 파일을 실제로 읽었는지 본다 — 안 쓰는 프리미티브를 지워도 안 깨진다.
    expect(Object.keys(UI_SOURCES)).toEqual(
      expect.arrayContaining([
        "../../../../../../packages/ui/src/components/dialog.tsx",
        "../../../../../../packages/ui/src/components/alert-dialog.tsx",
      ]),
    );
  });

  it("주석 제거·토큰 경계가 의도대로 동작한다", () => {
    expect(mutedTokensOnSurface('<DialogContent><div className="bg-muted/50 hover:bg-muted" />')).toEqual([
      "bg-muted/50",
      "bg-muted",
    ]);
    expect(mutedTokensOnSurface('<DialogContent>{/* bg-muted 금지 */}<span className="bg-muted-foreground" />')).toEqual(
      [],
    );
    expect(mutedTokensOnSurface('<input accept="image/*" /><DialogContent className="bg-muted" />')).toEqual([
      "bg-muted",
    ]);
    expect(mutedTokensOnSurface('<div className="bg-muted" />')).toEqual([]);
  });

  it("표면 표식이 있는 파일에 bg-muted가 없다", () => {
    const unexpected = OFFENDERS.filter(({ path }) => !(path in ALLOWLIST)).map(
      ({ path, tokens }) => `${path}: ${tokens.join(", ")}`,
    );
    expect(unexpected).toEqual([]);
  });

  it.each(Object.entries(ALLOWLIST))("허용 목록 %s — 걸리는 토큰이 기대 목록과 정확히 같다", (path, { tokens }) => {
    expect(path in ALL_SOURCES, `${path}가 glob에 없다 — 파일이 옮겨졌으면 키를 고친다`).toBe(true);
    expect(mutedTokensOnSurface(ALL_SOURCES[path] ?? "")).toEqual(tokens);
  });
});
