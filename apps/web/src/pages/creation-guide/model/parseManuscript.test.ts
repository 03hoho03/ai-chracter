import { describe, expect, it } from "vitest";

import { parseManuscript } from "./parseManuscript";

const FENCE = "````";

function md(...lines: string[]): string {
  return lines.join("\n");
}

/** 단계 절 하나에 칸 블록 하나를 둔 원고. 블록 안쪽 줄만 바꿔 가며 쓴다. */
function inField(header: string, ...body: string[]): string {
  return md("## 1단계 · 프로필 {#profile}", header, ...body, ":::");
}

const ONE_LINER_VALUE = [`${FENCE}value profile.oneLiner seed=tutorial-filmclub:oneLiner`, "상영회까지 여섯 주.", FENCE];

describe("parseManuscript — sections and prose", () => {
  it("splits sections, prose and prose examples in order", () => {
    const { sections } = parseManuscript(
      md(
        "## 들어가며 {#overview}",
        "들어가는 글",
        "",
        `${FENCE}field seed=tutorial-filmclub:oneLiner`,
        "상영회까지 여섯 주.",
        FENCE,
        "뒤 문단",
        "## 1단계 · 프로필 {#profile}",
        "프로필 글",
      ),
    );

    expect(sections).toEqual([
      {
        id: "overview",
        title: "들어가며",
        line: 1,
        summary: null,
        content: [
          { kind: "markdown", source: "들어가는 글\n" },
          {
            kind: "example",
            example: {
              kind: "field",
              source: { kind: "seed", slug: "tutorial-filmclub", path: "oneLiner" },
              body: "상영회까지 여섯 주.",
              line: 4,
            },
          },
          { kind: "markdown", source: "뒤 문단" },
        ],
      },
      { id: "profile", title: "1단계 · 프로필", line: 8, summary: null, content: [{ kind: "markdown", source: "프로필 글" }] },
    ]);
  });

  // 상태창은 백틱 세 개 펜스라, 바깥 펜스(네 개)를 닫지 않고 예시 본문에 원문 그대로 남아야 한다.
  it("keeps an inner three-backtick status fence as example content", () => {
    const body = ['*선배가 고개를 든다.* "왔어?"', "", "```", "장소: 동아리방", "```"].join("\n");
    const { sections } = parseManuscript(md("## 절 {#a}", `${FENCE}chat free`, body, FENCE));
    expect(sections[0]?.content).toEqual([
      { kind: "example", example: { kind: "chat", source: { kind: "free" }, body, line: 2 } },
    ]);
  });

  it("reads chat-user blocks and free examples", () => {
    const { sections } = parseManuscript(md("## 절 {#a}", `${FENCE}chat-user free`, "나도 갈래", FENCE));
    expect(sections[0]?.content).toEqual([
      { kind: "example", example: { kind: "chat-user", source: { kind: "free" }, body: "나도 갈래", line: 2 } },
    ]);
  });

  it("normalizes CRLF line endings before reading lines", () => {
    const { sections } = parseManuscript(`## 절 {#a}\r\n${FENCE}chat free\r\n한 줄\r\n두 줄\r\n${FENCE}\r\n`);
    expect(sections[0]?.content).toEqual([
      { kind: "example", example: { kind: "chat", source: { kind: "free" }, body: "한 줄\n두 줄", line: 2 } },
    ]);
  });

  it("drops whitespace-only prose between blocks", () => {
    const { sections } = parseManuscript(md("## 절 {#a}", `${FENCE}chat free`, "가", FENCE, "", `${FENCE}chat free`, "나", FENCE));
    expect(sections[0]?.content.map((item) => item.kind)).toEqual(["example", "example"]);
  });

  // id 가 없는 `##` 는 절이 아니다 — 본문에 남아 h2 가 되고, 원고 검사가 허용 태그 밖으로 실패시킨다.
  // 백틱 세 개 펜스도 본문에 남아 `pre` 로 실패한다.
  it.each([
    ["a level-two heading without an id", "## 아이디 없음"],
    ["a three-backtick fence", "```chat free\n글\n```"],
  ])("leaves %s as prose", (_label, source) => {
    const { sections } = parseManuscript(md("## 절 {#a}", source));
    expect(sections).toHaveLength(1);
    expect(sections[0]?.content).toEqual([{ kind: "markdown", source }]);
  });
});

describe("parseManuscript — blocks", () => {
  it("reads a field block with intro, value, details and bad parts", () => {
    const { sections } = parseManuscript(
      inField(
        "::: field profile.oneLiner",
        "보이는 설명",
        "",
        ...ONE_LINER_VALUE,
        "::: details",
        "자세히 글",
        "::: bad 세계관 몰아넣기",
        "나쁜 이유",
        "",
        `${FENCE}good profile.oneLiner seed=tutorial-filmclub:oneLiner`,
        "상영회까지 여섯 주.",
        FENCE,
        "",
        `${FENCE}value profile.oneLiner free`,
        "설정을 다 적은 한줄소개",
        FENCE,
      ),
    );

    expect(sections[0]?.content).toEqual([
      {
        kind: "field",
        id: "profile.oneLiner",
        keys: ["profile.oneLiner"],
        title: null,
        line: 2,
        intro: [{ kind: "markdown", source: "보이는 설명\n" }],
        values: [
          {
            key: "profile.oneLiner",
            source: { kind: "seed", slug: "tutorial-filmclub", path: "oneLiner" },
            body: "상영회까지 여섯 주.",
            line: 5,
          },
        ],
        details: [{ kind: "markdown", source: "자세히 글" }],
        bad: [
          {
            title: "세계관 몰아넣기",
            prose: [{ kind: "markdown", source: "나쁜 이유\n" }],
            values: [{ key: "profile.oneLiner", source: { kind: "free" }, body: "설정을 다 적은 한줄소개", line: 17 }],
            good: {
              key: "profile.oneLiner",
              source: { kind: "seed", slug: "tutorial-filmclub", path: "oneLiner" },
              body: "상영회까지 여섯 주.",
              line: 13,
            },
          },
        ],
      },
    ]);
  });

  it("reads a titled multi-key block and orders its values by key", () => {
    const { sections } = parseManuscript(
      inField(
        "::: field registration.target registration.visibility | 분류와 공개",
        `${FENCE}value registration.visibility seed=tutorial-filmclub:visibility`,
        '"public"',
        FENCE,
        `${FENCE}value registration.target seed=tutorial-filmclub:target`,
        '"male"',
        FENCE,
      ),
    );
    const [block] = sections[0]?.content ?? [];
    expect(block).toMatchObject({ kind: "field", title: "분류와 공개", id: "registration.target" });
    expect(block?.kind === "field" ? block.values.map((value) => value.key) : []).toEqual([
      "registration.target",
      "registration.visibility",
    ]);
  });

  it("reads a note block and the step summary", () => {
    const { sections } = parseManuscript(
      md("## 1단계 · 프로필 {#profile}", "", "::: summary 대표 이미지·이름", "리드", "::: note 발행 심사 {#publish-review}", "설명", "::: details", "더", ":::"),
    );
    expect(sections[0]).toMatchObject({
      summary: "대표 이미지·이름",
      content: [
        { kind: "markdown", source: "리드" },
        {
          kind: "note",
          id: "publish-review",
          title: "발행 심사",
          intro: [{ kind: "markdown", source: "설명" }],
          details: [{ kind: "markdown", source: "더" }],
        },
      ],
    });
  });

  // 목록 키 하나 + 그 목록 카드 안 칸들은 한 블록에 둘 수 있다(목록 머리 줄과 펼친 카드 한 장).
  it("accepts a list key together with keys inside its cards", () => {
    expect(() =>
      parseManuscript(
        inField(
          "::: field storySetting.developmentExamples storySetting.developmentExamples.*.userLine",
          `${FENCE}value storySetting.developmentExamples free`,
          '{ "cards": [{ "userLine": "가" }] }',
          FENCE,
          `${FENCE}value storySetting.developmentExamples.*.userLine free`,
          "가",
          FENCE,
        ),
      ),
    ).not.toThrow();
  });
});

describe("parseManuscript — strictness", () => {
  it.each([
    ["content before the first section", md("들어가는 글", "## 절 {#a}")],
    ["an example that never closes", md("## 절 {#a}", `${FENCE}chat free`, "글")],
    ["a fence without a source marker", md("## 절 {#a}", `${FENCE}chat`, "글", FENCE)],
    ["a misspelled example kind", md("## 절 {#a}", `${FENCE}chats free`, "글", FENCE)],
    ["a marker with trailing text", md("## 절 {#a}", `${FENCE}chat free 메모`, "글", FENCE)],
    ["an indented fence", md("## 절 {#a}", `  ${FENCE}chat free`, "  글", `  ${FENCE}`)],
    ["a fence inside a blockquote", md("## 절 {#a}", `> ${FENCE}chat free`, "> 글", `> ${FENCE}`)],
    ["a stray closing fence", md("## 절 {#a}", FENCE)],
    ["a good excerpt with a free source", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", `${FENCE}good profile.oneLiner free`, "글", FENCE)],
    ["a misspelled directive", md("## 절 {#a}", "::: feild profile.name")],
    ["an indented directive", md("## 절 {#a}", "  ::: details")],
    ["a directive inside a list item", md("## 절 {#a}", "- ::: details")],
    ["a directive inside a blockquote", md("## 절 {#a}", "> :::")],
    ["a value outside a block", md("## 절 {#a}", ...ONE_LINER_VALUE)],
    ["a details marker outside a block", md("## 절 {#a}", "::: details")],
    ["a close marker outside a block", md("## 절 {#a}", ":::")],
    ["a block left open at the end", md("## 1단계 · 프로필 {#profile}", "::: field profile.oneLiner", ...ONE_LINER_VALUE)],
    ["a block left open before a heading", md("## 1단계 · 프로필 {#profile}", "::: field profile.oneLiner", ...ONE_LINER_VALUE, "## 다음 {#b}")],
    ["a block opened inside a block", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: note 제목 {#x}")],
    ["a value for a key the block does not have", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, `${FENCE}value profile.name free`, "이름", FENCE)],
    ["two values for one key", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, ...ONE_LINER_VALUE)],
    ["a key without a value", inField("::: field profile.oneLiner profile.name", ...ONE_LINER_VALUE)],
    ["a field example in the block body", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, `${FENCE}field free`, "글", FENCE)],
    ["a good excerpt in the block body", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, `${FENCE}good profile.oneLiner seed=tutorial-filmclub:oneLiner`, "글", FENCE)],
    ["a value inside details", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: details", `${FENCE}value profile.oneLiner free`, "글", FENCE)],
    ["details after a bad part", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", `${FENCE}value profile.oneLiner free`, "글", FENCE, "::: details")],
    ["two details parts", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: details", "가", "::: details", "나")],
    ["a seed value in a bad part", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", ...ONE_LINER_VALUE)],
    ["a seed example in a bad part", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", `${FENCE}chat seed=tutorial-filmclub:oneLiner`, "글", FENCE)],
    ["a bad part with nothing free", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", "설명만 있다")],
    ["two good excerpts in a bad part", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", `${FENCE}value profile.oneLiner free`, "글", FENCE, `${FENCE}good profile.oneLiner seed=t:oneLiner`, "가", FENCE, `${FENCE}good profile.oneLiner seed=t:oneLiner`, "나", FENCE)],
    ["a good excerpt for a different key than the bad value", inField("::: field profile.oneLiner profile.name", ...ONE_LINER_VALUE, `${FENCE}value profile.name free`, "이름", FENCE, "::: bad 이름", `${FENCE}value profile.oneLiner free`, "글", FENCE, `${FENCE}good profile.name seed=t:name`, "가", FENCE)],
    ["a bad part in a note", md("## 1단계 · 프로필 {#profile}", "::: note 제목 {#x}", "글", "::: bad 이름", ":::")],
    ["a value in a note", md("## 1단계 · 프로필 {#profile}", "::: note 제목 {#x}", ...ONE_LINER_VALUE, ":::")],
    ["keys from different lists in one block", inField("::: field keywordNotes.*.name shortcuts.*.name")],
    ["a duplicated key in one block", inField("::: field profile.name profile.name")],
    ["a summary after prose", md("## 1단계 · 프로필 {#profile}", "리드", "::: summary 요약")],
    ["two summaries", md("## 1단계 · 프로필 {#profile}", "::: summary 요약", "::: summary 또")],
    ["a summary inside a block", inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: summary 요약")],
    [
      "a bad value missing its close fence before a chat example",
      inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 이름", `${FENCE}value profile.oneLiner free`, "나쁜 값", `${FENCE}chat free`, "대사", FENCE),
    ],
    [
      "a bad example missing its close fence before the next bad part",
      inField("::: field profile.oneLiner", ...ONE_LINER_VALUE, "::: bad 하나", `${FENCE}field free`, "글", "", "::: bad 둘", `${FENCE}value profile.oneLiner free`, "글", FENCE),
    ],
    ["a close fence with a trailing space", md("## 절 {#a}", `${FENCE}chat free`, "글", `${FENCE} `, "", `${FENCE}chat free`, "또", FENCE)],
  ])("throws on %s", (_label, source) => {
    expect(() => parseManuscript(source)).toThrow(/원고 \d+번째 줄/);
  });
});
