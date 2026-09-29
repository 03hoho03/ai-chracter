import { describe, expect, it } from "vitest";

import { parseManuscript } from "./parseManuscript";

const FENCE = "````";

describe("parseManuscript", () => {
  it("splits headings, prose and example blocks in order", () => {
    const { segments } = parseManuscript(
      [
        "들어가는 글",
        "",
        "## 1단계 · 프로필 {#profile}",
        "프로필 설명",
        `${FENCE}field seed=tutorial-filmclub:oneLiner`,
        "상영회까지 여섯 주.",
        FENCE,
        "뒤 문단",
      ].join("\n"),
    );

    expect(segments).toEqual([
      { kind: "markdown", source: "들어가는 글\n" },
      { kind: "heading", id: "profile", text: "1단계 · 프로필" },
      { kind: "markdown", source: "프로필 설명" },
      {
        kind: "example",
        exampleKind: "field",
        source: { kind: "seed", slug: "tutorial-filmclub", path: "oneLiner" },
        body: "상영회까지 여섯 주.",
      },
      { kind: "markdown", source: "뒤 문단" },
    ]);
  });

  it("builds the table of contents from headings", () => {
    const { toc } = parseManuscript("## 들어가며 {#intro}\n글\n## 설정 {#setting}\n글");
    expect(toc).toEqual([
      { id: "intro", text: "들어가며" },
      { id: "setting", text: "설정" },
    ]);
  });

  // 상태창은 백틱 세 개 펜스라, 바깥 펜스(네 개)를 닫지 않고 예시 본문에 원문 그대로 남아야 한다.
  it("keeps an inner three-backtick status fence as example content", () => {
    const body = ['*선배가 고개를 든다.* "왔어?"', "", "```", "장소: 동아리방", "```"].join("\n");
    const { segments } = parseManuscript(`${FENCE}chat seed=tutorial-filmclub:startingSetups.0.prologue\n${body}\n${FENCE}`);

    expect(segments).toEqual([
      {
        kind: "example",
        exampleKind: "chat",
        source: { kind: "seed", slug: "tutorial-filmclub", path: "startingSetups.0.prologue" },
        body,
      },
    ]);
  });

  it("reads chat-user blocks and free examples", () => {
    const { segments } = parseManuscript(`${FENCE}chat-user free\n나도 갈래\n${FENCE}`);
    expect(segments).toEqual([
      { kind: "example", exampleKind: "chat-user", source: { kind: "free" }, body: "나도 갈래" },
    ]);
  });

  it("normalizes CRLF line endings before reading lines", () => {
    const { segments } = parseManuscript(`${FENCE}chat free\r\n한 줄\r\n두 줄\r\n${FENCE}\r\n`);
    expect(segments).toEqual([
      { kind: "example", exampleKind: "chat", source: { kind: "free" }, body: "한 줄\n두 줄" },
    ]);
  });

  // 형식에서 벗어난 펜스는 예시 블록이 아니라 본문으로 남는다 — 렌더하면 코드 블록이 되고, 원고 검사가
  // 허용 태그 밖(`pre`)으로 실패시킨다. 조용히 인용 검사를 빠져나가지 않게 하는 장치다.
  it.each([
    ["a fence without a source marker", `${FENCE}chat\n글\n${FENCE}`],
    ["a misspelled kind", `${FENCE}chats free\n글\n${FENCE}`],
    ["a three-backtick fence", "```chat free\n글\n```"],
    ["an indented fence", `  ${FENCE}chat free\n  글\n  ${FENCE}`],
    ["a marker with trailing text", `${FENCE}chat free 메모\n글\n${FENCE}`],
  ])("leaves %s as prose", (_label, source) => {
    const { segments } = parseManuscript(source);
    expect(segments.every((segment) => segment.kind === "markdown")).toBe(true);
  });

  // id 가 없는 `##` 은 절이 아니다 — 본문에 남아 h2 가 되고, 원고 검사가 허용 태그 밖으로 실패시킨다.
  it("leaves a level-two heading without an id as prose", () => {
    const { segments, toc } = parseManuscript("## 아이디 없음\n글");
    expect(toc).toEqual([]);
    expect(segments).toEqual([{ kind: "markdown", source: "## 아이디 없음\n글" }]);
  });

  it("throws on an example block that never closes", () => {
    expect(() => parseManuscript(`${FENCE}chat free\n글`)).toThrow("예시 블록이 닫히지 않았다");
  });

  it("drops whitespace-only prose between blocks", () => {
    const { segments } = parseManuscript(`${FENCE}chat free\n가\n${FENCE}\n\n${FENCE}chat-user free\n나\n${FENCE}`);
    expect(segments.map((segment) => segment.kind)).toEqual(["example", "example"]);
  });
});
