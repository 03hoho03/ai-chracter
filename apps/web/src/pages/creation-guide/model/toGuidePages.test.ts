import { describe, expect, it } from "vitest";

import { STORY_FIELD_MOCKUPS } from "../config/storyFieldMockups";
import type { GuideTopic } from "../config/topics";
import { parseManuscript } from "./parseManuscript";
import { legacyStepFromHash, toDisplayItems, toGuidePages } from "./toGuidePages";

const FENCE = "````";

const STEPS = [
  { id: "profile", label: "프로필" },
  { id: "setting", label: "설정" },
];

const PLAIN_TOPIC: GuideTopic = { id: "character", title: "가이드", manuscript: "", steps: STEPS };
const BLOCK_TOPIC: GuideTopic = { ...PLAIN_TOPIC, id: "story", fieldMockups: STORY_FIELD_MOCKUPS };

function md(...lines: string[]): string {
  return lines.join("\n");
}

function pagesOf(source: string, topic: GuideTopic = PLAIN_TOPIC) {
  return toGuidePages(parseManuscript(source), topic);
}

const NAME_BLOCK = ["::: field profile.name", `${FENCE}value profile.name free`, "이름", FENCE, ":::"];

describe("toGuidePages", () => {
  it("splits overview sections around the steps and links neighbours", () => {
    const pages = pagesOf(
      md(
        "## 들어가며 {#overview}",
        "앞 글",
        "## 1단계 · 프로필 {#profile}",
        "### 소제목",
        "",
        "**프로필** 첫 문단",
        "## 2단계 · 설정 {#setting}",
        "설정 글",
        "## 자주 하는 실수 {#mistakes}",
        "뒤 글",
      ),
    );

    expect(pages.overview.before.map((section) => section.id)).toEqual(["overview"]);
    expect(pages.overview.after.map((section) => section.id)).toEqual(["mistakes"]);
    expect(pages.steps.map(({ id, index, title, summary, lead, prevId, nextId }) => ({ id, index, title, summary, lead, prevId, nextId }))).toEqual([
      { id: "profile", index: 0, title: "1단계 · 프로필", summary: "프로필 첫 문단", lead: null, prevId: null, nextId: "setting" },
      { id: "setting", index: 1, title: "2단계 · 설정", summary: "설정 글", lead: null, prevId: "profile", nextId: null },
    ]);
  });

  it("takes the summary marker and the lead paragraph apart for block topics", () => {
    const pages = pagesOf(
      md("## 1단계 · 프로필 {#profile}", "::: summary 짧은 요약", "리드 문단", ...NAME_BLOCK, "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드", "::: note 메모 {#memo}", "글", ":::"),
      BLOCK_TOPIC,
    );
    const [profile, setting] = pages.steps;
    expect(profile).toMatchObject({ summary: "짧은 요약", lead: "리드 문단" });
    expect(profile?.content.map((item) => item.kind)).toEqual(["field"]);
    expect(setting?.content.map((item) => item.kind)).toEqual(["note"]);
    expect([...pages.anchorOfKey]).toEqual([["profile.name", { stepId: "profile", anchorId: "profile.name" }]]);
  });

  it.each([
    ["steps out of builder order", md("## 2단계 · 설정 {#setting}", "가", "## 1단계 · 프로필 {#profile}", "나"), PLAIN_TOPIC],
    ["a missing step", md("## 1단계 · 프로필 {#profile}", "가"), PLAIN_TOPIC],
    ["steps split by another section", md("## 1단계 · 프로필 {#profile}", "가", "## 사이 {#between}", "## 2단계 · 설정 {#setting}"), PLAIN_TOPIC],
    ["a step repeated after the steps", md("## 1단계 · 프로필 {#profile}", "## 2단계 · 설정 {#setting}", "## 2단계 · 설정 {#setting}"), PLAIN_TOPIC],
    ["a step title that is not the tab label", md("## 1단계 · 프로필 설정 {#profile}", "## 2단계 · 설정 {#setting}"), PLAIN_TOPIC],
    ["a block outside the steps", md("## 들어가며 {#overview}", ...NAME_BLOCK, "## 1단계 · 프로필 {#profile}", "## 2단계 · 설정 {#setting}"), BLOCK_TOPIC],
    ["a summary outside the steps", md("## 들어가며 {#overview}", "::: summary 요약", "## 1단계 · 프로필 {#profile}", "## 2단계 · 설정 {#setting}"), PLAIN_TOPIC],
    ["a block in a topic without mockups", md("## 1단계 · 프로필 {#profile}", ...NAME_BLOCK, "## 2단계 · 설정 {#setting}"), PLAIN_TOPIC],
    ["a block step without a summary", md("## 1단계 · 프로필 {#profile}", "리드", ...NAME_BLOCK, "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드"), BLOCK_TOPIC],
    ["a block step without a lead", md("## 1단계 · 프로필 {#profile}", "::: summary 요약", ...NAME_BLOCK, "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드"), BLOCK_TOPIC],
    ["prose between blocks", md("## 1단계 · 프로필 {#profile}", "::: summary 요약", "리드", ...NAME_BLOCK, "떠 있는 글", "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드"), BLOCK_TOPIC],
    ["a key unknown to the mockup table", md("## 1단계 · 프로필 {#profile}", "::: summary 요약", "리드", "::: field profile.nickname", `${FENCE}value profile.nickname free`, "가", FENCE, ":::", "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드"), BLOCK_TOPIC],
    ["one key in two blocks", md("## 1단계 · 프로필 {#profile}", "::: summary 요약", "리드", ...NAME_BLOCK, ...NAME_BLOCK, "## 2단계 · 설정 {#setting}", "::: summary 둘", "리드"), BLOCK_TOPIC],
  ])("throws on %s", (_label, source, topic) => {
    expect(() => pagesOf(source, topic)).toThrow();
  });
});

describe("toDisplayItems", () => {
  function itemsOf(...lines: string[]) {
    const [section] = parseManuscript(md("## 절 {#a}", ...lines)).sections;
    return (section?.content ?? []).flatMap((item) => (item.kind === "markdown" || item.kind === "example" ? [item] : []));
  }

  it("merges consecutive chat and chat-user examples into one conversation", () => {
    const display = toDisplayItems(
      itemsOf(`${FENCE}chat free`, "왔어?", FENCE, `${FENCE}chat-user free`, "응", FENCE, `${FENCE}chat free`, "앉아", FENCE),
    );
    expect(display).toEqual([
      {
        kind: "conversation",
        messages: [
          { role: "character", body: "왔어?" },
          { role: "user", body: "응" },
          { role: "character", body: "앉아" },
        ],
      },
    ]);
  });

  it("starts a new conversation after prose or a field example", () => {
    const display = toDisplayItems(
      itemsOf(
        `${FENCE}chat free`,
        "하나",
        FENCE,
        "사이 글",
        `${FENCE}chat free`,
        "둘",
        FENCE,
        `${FENCE}field free`,
        "*입력*",
        FENCE,
        `${FENCE}chat free`,
        "셋",
        FENCE,
      ),
    );
    expect(display.map((item) => item.kind)).toEqual(["conversation", "markdown", "conversation", "field", "conversation"]);
  });
});

describe("legacyStepFromHash", () => {
  const stepIds = ["profile", "setting"];

  it("maps a tab-id hash from the old single-page guide to its step", () => {
    expect(legacyStepFromHash("#setting", stepIds)).toBe("setting");
  });

  // 개요 안의 앵커는 단계 페이지로 보내지 않는다 — 보내면 개요 안 이동이 다른 페이지로 튄다.
  it.each(["", "#", "#preview", "#mistakes", "#overview", "#Setting", "#setting-notation"])("leaves %j alone", (hash) => {
    expect(legacyStepFromHash(hash, stepIds)).toBeNull();
  });
});
