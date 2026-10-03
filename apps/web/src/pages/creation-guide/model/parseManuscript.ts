import { assertNever } from "@/shared/lib/assertNever";

/**
 * 작성 가이드 원고(마크다운)를 절·칸 블록·예시 조각으로 나눈다.
 *
 * 렌더러와 원고 검사 테스트가 이 함수 하나를 같이 쓴다. 인용 대조 테스트는 렌더러가 "예시"로 그리는 것과 정확히 같은
 * 것을 검사해야 하는데, 그 판정이 React 컴포넌트 안에 있으면 node 환경 테스트가 그것을 볼 수 없다. 그래서 판정을 순수
 * 함수로 둔다. 표기가 조금이라도 틀리면 조용히 본문으로 흘려보내지 않고 줄 번호를 단 오류를 던진다 — 틀린 표기가 화면에
 * 글자로 새거나 인용 검사를 빠져나가는 길을 막기 위해서다.
 *
 * 원고 표기(펜스 본문 밖에서, 위에서부터 첫 일치):
 * - `## 제목 {#id}` — 절. 단계 절이면 id 가 빌더 탭 id 다. id 없는 `##` 는 본문으로 남고 허용 태그 검사가 실패시킨다.
 * - `::: summary 짧은 요약` — 절 제목 바로 다음(빈 줄 제외 첫 줄)에만 쓰는 한 줄 표기. 개요 페이지의 단계 행 둘째 줄에
 *   쓰는 짧은 요약이다. 단계 머리의 리드 문단과 길이 상한이 달라(리드는 두 줄, 요약은 한 줄) 따로 둔다. 닫는 줄이 없다.
 * - 백틱 네 개 펜스 — 예시. `chat`·`chat-user`·`field` 는 산문 속 예시(채팅 말풍선·입력 원문), `value <칸 키>` 는 칸
 *   목업에 채울 값, `good <칸 키>` 는 나쁜 예와 견주는 좋은 쪽 발췌다. 출처는 `seed=<slug>:<JSON 경로>` 또는 `free`
 *   (`good` 은 seed 만). 닫는 줄은 백틱 네 개뿐이고 안쪽은 원문 그대로라 상태창 펜스(백틱 세 개)가 들어가도 끝나지 않는다.
 *   안쪽에 백틱 네 개로 시작하는 줄이 있으면 오류다(닫는 줄 누락·꼬리 글).
 * - `::: field <칸 키>… [| 제목]` … `:::` — 칸 블록. 본문은 보이는 설명·목업 값, 이어서 `::: details`(자세히, 0~1)와
 *   `::: bad 이름`(나쁜 예, 0~n)이 올 수 있다. 칸 키는 폼 경로이고 배열 위치는 `*` 다.
 * - `::: note 제목 {#id}` … `:::` — 칸에 붙지 않는 블록. 설명과 `::: details` 0~1 만 둔다.
 * - 줄 어디에든 `:::` 가 있는데 위 표기와 정확히 맞지 않거나, 줄 머리(들여쓰기·인용 표시 뒤 포함)에 백틱 네 개가 위
 *   표기와 맞지 않으면 오류다. 백틱 세 개 펜스는 본문으로 남아 허용 태그 검사가 `pre` 로 실패시킨다.
 */

export type ExampleSource = { kind: "seed"; slug: string; path: string } | { kind: "free" };

/** 산문 속 예시 종류. 여는 줄 정규식의 선택지도 이 목록에서 만든다. */
export const PROSE_EXAMPLE_KINDS = ["chat", "chat-user", "field"] as const;

export type ProseExampleKind = (typeof PROSE_EXAMPLE_KINDS)[number];

export type ProseExample = { kind: ProseExampleKind; source: ExampleSource; body: string; line: number };

export type GuideItem = { kind: "markdown"; source: string } | { kind: "example"; example: ProseExample };

export type FieldValue = { key: string; source: ExampleSource; body: string; line: number };

export type FieldBadPart = { title: string; prose: GuideItem[]; values: FieldValue[]; good: FieldValue | null };

export type GuideFieldBlock = {
  kind: "field";
  /** 블록 앵커 id. 첫 칸 키 원문이다(`*`·`.`·`$` 는 HTML id 와 URL 조각에서 그대로 쓸 수 있다). */
  id: string;
  keys: string[];
  title: string | null;
  line: number;
  intro: GuideItem[];
  /** `keys` 순서. */
  values: FieldValue[];
  details: GuideItem[] | null;
  bad: FieldBadPart[];
};

export type GuideNoteBlock = {
  kind: "note";
  id: string;
  title: string;
  line: number;
  intro: GuideItem[];
  details: GuideItem[] | null;
};

export type SectionContent = GuideItem | GuideFieldBlock | GuideNoteBlock;

export type ManuscriptSection = {
  id: string;
  title: string;
  line: number;
  summary: string | null;
  content: SectionContent[];
};

export type Manuscript = { sections: ManuscriptSection[] };

const KEY = String.raw`[A-Za-z$][\w$]*(?:\.(?:\*|[A-Za-z$][\w$]*))*`;
const SOURCE = String.raw`(?:seed=([^\s:]+):(\S+)|(free))`;
const ID = String.raw`[A-Za-z][\w-]*`;
const TITLE = String.raw`\S(?:.*\S)?`;

/** 펜스 여는 줄·닫는 줄의 백틱 네 개. */
const FENCE = "````";

const HEADING_LINE = new RegExp(`^## (${TITLE}) \\{#(${ID})\\}$`);
const PROSE_EXAMPLE_LINE = new RegExp(`^${FENCE}(${PROSE_EXAMPLE_KINDS.join("|")}) ${SOURCE}$`);
const VALUE_LINE = new RegExp(`^${FENCE}value (${KEY}) ${SOURCE}$`);
const GOOD_LINE = new RegExp(`^${FENCE}good (${KEY}) seed=([^\\s:]+):(\\S+)$`);
const ANY_FENCE_LINE = new RegExp(`^[ \\t>]*${FENCE}`);
const SUMMARY_LINE = new RegExp(`^::: summary (${TITLE})$`);
const FIELD_LINE = new RegExp(`^::: field (${KEY}(?: ${KEY})*)(?: \\| (${TITLE}))?$`);
const NOTE_LINE = new RegExp(`^::: note (${TITLE}) \\{#(${ID})\\}$`);
const DETAILS_LINE = /^::: details$/;
const BAD_LINE = new RegExp(`^::: bad (${TITLE})$`);
const CLOSE_LINE = /^:::$/;
const ANY_DIRECTIVE = /:::/;

type Fence =
  | { kind: "prose"; example: Omit<ProseExample, "body" | "line"> }
  | { kind: "value"; key: string; source: ExampleSource }
  | { kind: "good"; key: string; source: ExampleSource };

type Directive =
  | { kind: "heading"; title: string; id: string }
  | { kind: "summary"; text: string }
  | { kind: "field"; keys: string[]; title: string | null }
  | { kind: "note"; title: string; id: string }
  | { kind: "details" }
  | { kind: "bad"; title: string }
  | { kind: "close" };

type OpenBlock =
  | { kind: "field"; block: GuideFieldBlock; part: "main" | "details" | "bad" }
  | { kind: "note"; block: GuideNoteBlock; part: "main" | "details" };

export function parseManuscript(markdown: string): Manuscript {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const sections: ManuscriptSection[] = [];
  let section: ManuscriptSection | undefined;
  let open: OpenBlock | undefined;
  let proseLines: string[] = [];

  function fail(lineIndex: number, message: string): never {
    throw new Error(`원고 ${lineIndex + 1}번째 줄: ${message} — ${lines[lineIndex] ?? ""}`);
  }

  /** 산문·예시 조각을 지금 자리(블록 안이면 그 부분, 아니면 절 본문)에 붙인다. */
  function pushItem(item: GuideItem, lineIndex: number) {
    itemsHere(lineIndex).push(item);
  }

  function itemsHere(lineIndex: number): { push: (item: GuideItem) => void } {
    if (open?.kind === "field") {
      if (open.part === "main") return open.block.intro;
      const lastBad = open.block.bad.at(-1);
      if (open.part === "bad" && lastBad) return lastBad.prose;
      if (open.part === "details" && open.block.details) return open.block.details;
    } else if (open?.kind === "note") {
      if (open.part === "main") return open.block.intro;
      if (open.block.details) return open.block.details;
    } else if (section) {
      return section.content;
    }
    return fail(lineIndex, "조각을 붙일 자리가 없다");
  }

  function flushProse(lineIndex: number) {
    const source = proseLines.join("\n");
    proseLines = [];
    if (source.trim() === "") return;
    pushItem({ kind: "markdown", source }, lineIndex);
  }

  function closeBlock(lineIndex: number) {
    if (!open) return;
    if (open.kind === "field") checkFieldBlock(open.block, lineIndex);
    open = undefined;
  }

  function checkFieldBlock(block: GuideFieldBlock, lineIndex: number) {
    const missing = block.keys.filter((key) => !block.values.some((value) => value.key === key));
    if (missing.length > 0) fail(lineIndex, `칸 블록(${block.line}번째 줄)에 값이 없는 칸 키: ${missing.join(", ")}`);
    block.values.sort((a, b) => block.keys.indexOf(a.key) - block.keys.indexOf(b.key));
    for (const part of block.bad) {
      const hasFreeExample = part.prose.some((item) => item.kind === "example");
      if (part.values.length === 0 && !hasFreeExample) {
        fail(lineIndex, `나쁜 예 "${part.title}" 에 free 값이나 free 예시가 없다`);
      }
      const badKeys = new Set(part.values.map((value) => value.key));
      if (part.good && badKeys.size > 0 && !badKeys.has(part.good.key)) {
        fail(lineIndex, `나쁜 예 "${part.title}" 의 좋은 쪽 발췌가 나쁜 값과 다른 칸 키다: ${part.good.key}`);
      }
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";

    const fence = readFence(line, () => fail(index, "알 수 없는 예시 블록 표기"));
    if (fence) {
      const closeIndex = lines.indexOf(FENCE, index + 1);
      if (closeIndex === -1) fail(index, "예시 블록이 닫히지 않았다");
      // 백틱 네 개로 시작하는 줄은 시드 값에도 예시 글에도 나올 일이 없다. 본문에 그런 줄이 있으면 닫는 줄을 빠뜨려 다음
      // 펜스까지 삼켰거나 닫는 줄에 다른 글자(꼬리 공백 포함)가 붙은 것이라, 조용히 본문으로 두지 않는다.
      for (let bodyIndex = index + 1; bodyIndex < closeIndex; bodyIndex += 1) {
        if (ANY_FENCE_LINE.test(lines[bodyIndex] ?? "")) {
          fail(bodyIndex, "예시 블록 안에 펜스 줄이 있다 — 닫는 줄을 빠뜨렸거나 닫는 줄에 다른 글자가 붙었다");
        }
      }
      const body = lines.slice(index + 1, closeIndex).join("\n");
      if (!section) fail(index, "첫 절 제목 앞에 내용이 있다");
      flushProse(index);
      placeFence(fence, body, index);
      index = closeIndex;
      continue;
    }

    const directive = readDirective(line, () => fail(index, "알 수 없는 블록 표기"));
    if (!directive) {
      if (!section && line.trim() !== "") fail(index, "첫 절 제목 앞에 내용이 있다");
      proseLines.push(line);
      continue;
    }

    flushProse(index);
    switch (directive.kind) {
      case "heading":
      case "field":
      case "note":
      case "summary":
        if (open) fail(index, `블록(${open.block.line}번째 줄)이 \`:::\` 로 닫히지 않았다`);
        break;
      default:
        break;
    }

    switch (directive.kind) {
      case "heading":
        section = { id: directive.id, title: directive.title, line: index + 1, summary: null, content: [] };
        sections.push(section);
        break;
      case "summary":
        if (!section) fail(index, "첫 절 제목 앞에 내용이 있다");
        if (section.summary !== null || section.content.length > 0) {
          fail(index, "요약 표기는 절 제목 바로 다음에 한 번만 쓴다");
        }
        section.summary = directive.text;
        break;
      case "field": {
        if (!section) fail(index, "첫 절 제목 앞에 내용이 있다");
        if (new Set(directive.keys).size !== directive.keys.length) fail(index, "칸 키가 중복됐다");
        if (!isOneListFamily(directive.keys)) fail(index, "한 블록의 칸 키들이 같은 목록 계열이 아니다");
        const block: GuideFieldBlock = {
          kind: "field",
          id: directive.keys[0] ?? "",
          keys: directive.keys,
          title: directive.title,
          line: index + 1,
          intro: [],
          values: [],
          details: null,
          bad: [],
        };
        section.content.push(block);
        open = { kind: "field", block, part: "main" };
        break;
      }
      case "note": {
        if (!section) fail(index, "첫 절 제목 앞에 내용이 있다");
        const block: GuideNoteBlock = {
          kind: "note",
          id: directive.id,
          title: directive.title,
          line: index + 1,
          intro: [],
          details: null,
        };
        section.content.push(block);
        open = { kind: "note", block, part: "main" };
        break;
      }
      case "details":
        if (!open) fail(index, "블록 밖의 자세히 표기");
        if (open.part !== "main") fail(index, "자세히는 블록 본문 바로 뒤에 한 번만 쓴다(나쁜 예보다 앞)");
        open.block.details = [];
        open.part = "details";
        break;
      case "bad":
        if (open?.kind !== "field") fail(index, "나쁜 예는 칸 블록 안에만 쓴다");
        open.block.bad.push({ title: directive.title, prose: [], values: [], good: null });
        open.part = "bad";
        break;
      case "close":
        if (!open) fail(index, "열린 블록이 없는데 닫는 표기가 있다");
        closeBlock(index);
        break;
      default:
        assertNever(directive);
    }
  }

  flushProse(lines.length - 1);
  if (open) fail(lines.length - 1, `블록(${open.block.line}번째 줄)이 \`:::\` 로 닫히지 않은 채 원고가 끝났다`);
  return { sections };

  function placeFence(fence: Fence, body: string, index: number) {
    const line = index + 1;
    if (fence.kind === "prose") {
      const example: ProseExample = { ...fence.example, body, line };
      if (open?.kind === "field" && open.part === "main" && example.kind === "field") {
        fail(index, "칸 블록 본문에는 field 예시 대신 value 를 쓴다");
      }
      if (open?.kind === "field" && open.part === "bad" && example.source.kind !== "free") {
        fail(index, "나쁜 예의 예시는 free 만 쓴다");
      }
      pushItem({ kind: "example", example }, index);
      return;
    }

    if (open?.kind !== "field") fail(index, "목업 값·좋은 쪽 발췌는 칸 블록 안에만 쓴다");
    const block = open.block;
    if (!block.keys.includes(fence.key)) fail(index, `블록에 없는 칸 키: ${fence.key}`);
    const value: FieldValue = { key: fence.key, source: fence.source, body, line };

    if (fence.kind === "value") {
      if (open.part === "main") {
        if (block.values.some((existing) => existing.key === fence.key)) fail(index, `같은 칸 키의 값이 둘이다: ${fence.key}`);
        block.values.push(value);
        return;
      }
      if (open.part === "bad") {
        if (fence.source.kind !== "free") fail(index, "나쁜 예의 값은 free 만 쓴다");
        lastBadPart(block, index).values.push(value);
        return;
      }
      fail(index, "자세히 안에는 목업 값을 쓰지 않는다");
    }

    if (open.part !== "bad") fail(index, "좋은 쪽 발췌는 나쁜 예 안에만 쓴다");
    const part = lastBadPart(block, index);
    if (part.good) fail(index, "나쁜 예 하나에 좋은 쪽 발췌는 하나만 쓴다");
    part.good = value;
  }

  function lastBadPart(block: GuideFieldBlock, index: number): FieldBadPart {
    const part = block.bad.at(-1);
    if (!part) fail(index, "나쁜 예 밖");
    return part;
  }
}

function readFence(line: string, onUnknown: () => never): Fence | undefined {
  const prose = PROSE_EXAMPLE_LINE.exec(line);
  if (prose) {
    return { kind: "prose", example: { kind: toProseExampleKind(prose[1]), source: toSource(prose[2], prose[3]) } };
  }
  const value = VALUE_LINE.exec(line);
  if (value) return { kind: "value", key: value[1] ?? "", source: toSource(value[2], value[3]) };
  const good = GOOD_LINE.exec(line);
  if (good) return { kind: "good", key: good[1] ?? "", source: toSource(good[2], good[3]) };
  if (ANY_FENCE_LINE.test(line)) return onUnknown();
  return undefined;
}

function readDirective(line: string, onUnknown: () => never): Directive | undefined {
  const heading = HEADING_LINE.exec(line);
  if (heading) return { kind: "heading", title: heading[1] ?? "", id: heading[2] ?? "" };
  if (!ANY_DIRECTIVE.test(line)) return undefined;

  const summary = SUMMARY_LINE.exec(line);
  if (summary) return { kind: "summary", text: summary[1] ?? "" };
  const field = FIELD_LINE.exec(line);
  if (field) return { kind: "field", keys: (field[1] ?? "").split(" "), title: field[2] ?? null };
  const note = NOTE_LINE.exec(line);
  if (note) return { kind: "note", title: note[1] ?? "", id: note[2] ?? "" };
  if (DETAILS_LINE.test(line)) return { kind: "details" };
  const bad = BAD_LINE.exec(line);
  if (bad) return { kind: "bad", title: bad[1] ?? "" };
  if (CLOSE_LINE.test(line)) return { kind: "close" };
  return onUnknown();
}

function toProseExampleKind(value: string | undefined): ProseExampleKind {
  const kind = PROSE_EXAMPLE_KINDS.find((candidate) => candidate === value);
  if (kind) return kind;
  throw new Error(`알 수 없는 예시 블록 종류: ${value}`);
}

function toSource(slug: string | undefined, path: string | undefined): ExampleSource {
  if (slug !== undefined && path !== undefined) return { kind: "seed", slug, path };
  return { kind: "free" };
}

/**
 * 블록 칸 키의 목록 계열 — 마지막 `*` 까지의 앞부분. 다른 키의 목록 자체인 키(전개 예시 목록 + 카드 안 두 칸)는 그
 * 목록의 `*` 계열로 본다. 서로 다른 목록의 칸을 한 블록에 섞으면 목업이 어느 카드의 값인지 말할 수 없어서 막는다.
 */
function isOneListFamily(keys: readonly string[]): boolean {
  const families = keys.map((key) => {
    const isListOfOthers = keys.some((other) => other.startsWith(`${key}.*.`));
    if (isListOfOthers) return `${key}.*`;
    const lastStar = key.lastIndexOf(".*");
    return lastStar === -1 ? "" : key.slice(0, lastStar + 2);
  });
  return new Set(families).size <= 1;
}
