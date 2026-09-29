/**
 * 작성 가이드 원고(마크다운)를 제목·본문·예시 블록 조각으로 나눈다.
 *
 * 렌더러와 원고 검사 테스트가 이 함수 하나를 같이 쓴다. 인용 대조 테스트는 렌더러가 "예시 블록"으로
 * 그리는 것과 정확히 같은 것을 검사해야 하는데, 그 판정이 React 컴포넌트 안에 있으면 테스트가 페이지를
 * 렌더해야 하고 node 환경에서는 그게 안 된다. 그래서 판정을 순수 함수로 둔다.
 *
 * 원고 표기:
 * - `## 제목 {#id}` — 절 제목. id 는 목차와 앵커에 쓰고, 단계 절이면 빌더 탭 id 와 같다.
 * - 줄 머리의 백틱 네 개 펜스 ```` ````chat seed=<slug>:<JSON 경로> ```` / `free` — 예시 블록. 종류는
 *   `chat`(캐릭터 메시지)·`chat-user`(사용자 메시지)·`field`(빌더 칸에 입력하는 원문)이고, 닫는 줄은
 *   백틱 네 개뿐이다. 안쪽은 원문 그대로라 상태창 펜스(백틱 세 개)가 들어가도 블록이 끝나지 않는다.
 * - 그 밖의 줄은 전부 일반 본문이다. 형식이 틀린 펜스(종류 오타·백틱 세 개·들여쓰기)와 id 없는 `##` 는
 *   본문으로 남아 코드 블록·h2 가 되고, 허용 태그 검사가 그것을 실패시킨다.
 */

/** 예시 블록 종류. 여는 줄 정규식의 선택지도 이 목록에서 만든다. */
export const EXAMPLE_KINDS = ["chat", "chat-user", "field"] as const;

export type ExampleKind = (typeof EXAMPLE_KINDS)[number];

export type ExampleSource = { kind: "seed"; slug: string; path: string } | { kind: "free" };

export type ManuscriptSegment =
  | { kind: "heading"; id: string; text: string }
  | { kind: "markdown"; source: string }
  | { kind: "example"; exampleKind: ExampleKind; source: ExampleSource; body: string };

export type ManuscriptTocEntry = { id: string; text: string };

export type Manuscript = {
  toc: ManuscriptTocEntry[];
  segments: ManuscriptSegment[];
};

const HEADING_LINE = /^## (.+) \{#([A-Za-z][\w-]*)\}$/;
/** 예시 블록의 바깥 펜스(백틱 네 개). 닫는 줄은 이것 하나뿐이다. */
const EXAMPLE_FENCE = "````";
const EXAMPLE_OPEN_LINE = new RegExp(
  `^${EXAMPLE_FENCE}(${EXAMPLE_KINDS.join("|")}) (?:seed=([^\\s:]+):(\\S+)|(free))$`,
);

export function parseManuscript(markdown: string): Manuscript {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const segments: ManuscriptSegment[] = [];
  let markdownLines: string[] = [];

  function flushMarkdown() {
    const source = markdownLines.join("\n");
    if (source.trim() !== "") segments.push({ kind: "markdown", source });
    markdownLines = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";

    const heading = HEADING_LINE.exec(line);
    if (heading) {
      flushMarkdown();
      segments.push({ kind: "heading", id: heading[2] ?? "", text: (heading[1] ?? "").trim() });
      continue;
    }

    const opening = EXAMPLE_OPEN_LINE.exec(line);
    if (opening) {
      flushMarkdown();
      const closeIndex = lines.indexOf(EXAMPLE_FENCE, index + 1);
      if (closeIndex === -1) {
        throw new Error(`예시 블록이 닫히지 않았다(${index + 1}번째 줄): ${line}`);
      }
      segments.push({
        kind: "example",
        exampleKind: toExampleKind(opening[1]),
        source: toExampleSource(opening),
        body: lines.slice(index + 1, closeIndex).join("\n"),
      });
      index = closeIndex;
      continue;
    }

    markdownLines.push(line);
  }
  flushMarkdown();

  const toc = segments.flatMap((segment) =>
    segment.kind === "heading" ? [{ id: segment.id, text: segment.text }] : [],
  );
  return { toc, segments };
}

function toExampleKind(value: string | undefined): ExampleKind {
  const kind = EXAMPLE_KINDS.find((candidate) => candidate === value);
  if (kind) return kind;
  throw new Error(`알 수 없는 예시 블록 종류: ${value}`);
}

function toExampleSource(opening: RegExpExecArray): ExampleSource {
  const [, , slug, path] = opening;
  if (slug !== undefined && path !== undefined) return { kind: "seed", slug, path };
  return { kind: "free" };
}
