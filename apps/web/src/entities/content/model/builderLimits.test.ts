import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  characterLimit,
  hashtagsSchema,
  MAX_CHARACTER_PROMPT_LENGTH,
  MAX_DESCRIPTION_LENGTH,
  MAX_DEVELOPMENT_EXAMPLES,
  MAX_EXAMPLE_DIALOGUE_LINE_LENGTH,
  MAX_EXAMPLE_DIALOGUES,
  MAX_HASHTAG_LENGTH,
  MAX_HASHTAGS,
  MAX_INTRO_LENGTH,
  MAX_NAME_LENGTH,
  MAX_ONE_LINER_LENGTH,
  MAX_PLAY_GUIDE_LENGTH,
  MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH,
  MAX_STARTING_SETUPS,
  MAX_SUGGESTED_REPLIES,
} from "./builderLimits";

type LimitTable = Record<"common" | "character" | "story", Record<string, number>>;

// 서버가 검사에 쓰는 표를 모듈과 다른 길(상대 경로 글롭)로 직접 읽는다 — 상수가 엉뚱한 키를 읽어도 같은 길로 읽으면
// 대조가 함께 틀린다. 글롭은 파일 하나만 맞춘다.
const TABLE_FILES = import.meta.glob<LimitTable>("../../../../../api/src/api/content/builder_limits.json", {
  import: "default",
  eager: true,
});

function loadTable(): LimitTable {
  const [table] = Object.values(TABLE_FILES);
  if (table === undefined) throw new Error("builder_limits.json 을 찾지 못했다");
  return table;
}

describe("builder limits", () => {
  // [표의 구역.키, 화면이 쓰는 상수]
  const pairs: [string, number][] = [
    ["common.nameMaxLength", MAX_NAME_LENGTH],
    ["common.oneLinerMaxLength", MAX_ONE_LINER_LENGTH],
    ["common.descriptionMaxLength", MAX_DESCRIPTION_LENGTH],
    ["common.hashtagMaxCount", MAX_HASHTAGS],
    ["common.hashtagMaxLength", MAX_HASHTAG_LENGTH],
    ["character.introMaxLength", MAX_INTRO_LENGTH],
    ["character.characterPromptMaxLength", MAX_CHARACTER_PROMPT_LENGTH],
    ["character.playguideMaxLength", MAX_PLAY_GUIDE_LENGTH],
    ["character.exampleDialogueLineMaxLength", MAX_EXAMPLE_DIALOGUE_LINE_LENGTH],
    ["character.exampleDialogueMaxCount", MAX_EXAMPLE_DIALOGUES],
    ["character.situationalImageTriggerMaxLength", MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH],
    ["story.startingSetupMaxCount", MAX_STARTING_SETUPS],
    ["story.suggestedReplyMaxCount", MAX_SUGGESTED_REPLIES],
    ["story.developmentExampleMaxCount", MAX_DEVELOPMENT_EXAMPLES],
  ];

  it.each(pairs)("reads %s from the server's table", (key, value) => {
    const [section, name] = key.split(".");
    const table = loadTable();
    expect(section === "common" || section === "character" || section === "story").toBe(true);
    if (section !== "common" && section !== "character" && section !== "story") return;
    expect(value).toBe(table[section][name ?? ""]);
  });

  it("maps every limit in the table, so a new server limit cannot go unread", () => {
    const table = loadTable();
    const tableKeys = Object.entries(table).flatMap(([section, limits]) =>
      Object.keys(limits).map((name) => `${section}.${name}`),
    );
    expect(pairs.map(([key]) => key).sort()).toEqual(tableKeys.sort());
  });
});

describe("characterLimit", () => {
  const schema = z.string().refine(...characterLimit(3, "이름"));

  it("counts code points, so emoji count once the way the server does", () => {
    expect(schema.safeParse("😀😀😀").success).toBe(true);
    expect(schema.safeParse("😀😀😀😀").success).toBe(false);
  });

  it("picks the particle that fits the label", () => {
    expect(characterLimit(3, "이름")[1]).toBe("이름은 3자 이하로 입력해주세요");
    expect(characterLimit(3, "플레이가이드")[1]).toBe("플레이가이드는 3자 이하로 입력해주세요");
  });
});

describe("hashtagsSchema", () => {
  it("accepts up to the count and length limits", () => {
    const tags = Array.from({ length: MAX_HASHTAGS }, (_, i) => `${"가".repeat(MAX_HASHTAG_LENGTH - 1)}${i}`);
    expect(hashtagsSchema.safeParse(tags).success).toBe(true);
  });

  it("rejects one tag too many or one character too long, on the list itself", () => {
    const tooMany = hashtagsSchema.safeParse(Array.from({ length: MAX_HASHTAGS + 1 }, (_, i) => `태그${i}`));
    expect(tooMany.success).toBe(false);
    expect(tooMany.error?.issues[0]?.path).toEqual([]);
    expect(hashtagsSchema.safeParse(["가".repeat(MAX_HASHTAG_LENGTH + 1)]).success).toBe(false);
  });
});
