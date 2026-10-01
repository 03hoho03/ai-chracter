// 정규화·삭제 표는 서버 테스트 `apps/api/tests/test_media_tags.py` 의 행을 그대로 옮긴 것이다 — 빌더 미리보기의 첫
// 메시지는 이 구현으로, 실채팅의 첫 메시지는 서버 구현으로 정규화되므로 둘이 갈라지면 같은 글이 다르게 보인다. 서버
// 표에 행을 더하면 여기(정규화 표는 `mediaTagCases.ts`)에도 더한다.
import { describe, expect, it } from "vitest";

import {
  dropUnresolvedMediaTags,
  normalizeMediaTags,
  splitMediaTagText,
  stripMediaTags,
  type MediaTagImages,
} from "./mediaTags";
import { CELLS, MINA_CLASSROOM, MINA_ROOFTOP, NORMALIZE_CASES, UNKNOWN } from "./mediaTagCases";

const tag = (cellId: string) => `{{img::${cellId}}}`;

describe("normalizeMediaTags", () => {
  it.each(NORMALIZE_CASES)("%s", (_id, text, expectedText, expectedIds) => {
    const result = normalizeMediaTags(text, CELLS);
    expect(result.text).toBe(expectedText);
    expect([...result.cellIds].sort()).toEqual([...expectedIds].sort());
  });

  it("matches cell names given in NFD or with spaces", () => {
    const cells = [{ person: ` ${"민아".normalize("NFD")}`, scene: "교실 ", cellId: MINA_CLASSROOM }];
    expect(normalizeMediaTags("{{img::민아/교실}}", cells).text).toBe(tag(MINA_CLASSROOM));
  });

  it("folds the line left by a deleted tag", () => {
    expect(normalizeMediaTags("앞 문단\n\n{{img::수아/교실}}\n\n뒤 문단", CELLS).text).toBe("앞 문단\n\n뒤 문단");
  });
});

describe("stripMediaTags", () => {
  it.each<[string, string, string]>([
    ["name-form-alone", "{{img::민아/교실}}", ""],
    ["id-form-alone", tag(MINA_CLASSROOM), ""],
    ["mid-line-only-the-tag-goes", "앞 {{img::민아/교실}} 뒤", "앞  뒤"],
    ["id-form-mid-line", `앞${tag(UNKNOWN)}뒤`, "앞뒤"],
    ["tag-line-between-blank-lines", "앞 문단\n\n{{img::민아/교실}}\n\n뒤 문단", "앞 문단\n\n뒤 문단"],
    ["tag-line-without-blank-lines", "앞 문단\n{{img::민아/교실}}\n뒤 문단", "앞 문단\n뒤 문단"],
    ["tag-line-with-spaces", "앞 문단\n\n  {{img::민아/교실}}  \n\n뒤 문단", "앞 문단\n\n뒤 문단"],
    [
      "two-tag-lines-in-a-row",
      `앞 문단\n\n{{img::민아/교실}}\n${tag(MINA_ROOFTOP)}\n\n뒤 문단`,
      "앞 문단\n\n뒤 문단",
    ],
    ["leading-tag-line", "{{img::민아/교실}}\n\n본문", "본문"],
    ["trailing-tag-line", "본문\n\n{{img::민아/교실}}\n", "본문"],
    ["existing-blank-lines-kept", "앞 문단\n\n\n뒤 문단", "앞 문단\n\n\n뒤 문단"],
    [
      "blank-lines-kept-when-the-tag-line-keeps-text",
      "앞 문단\n\n\n중간 {{img::민아/교실}}\n\n\n뒤 문단",
      "앞 문단\n\n\n중간 \n\n\n뒤 문단",
    ],
    ["name-forms-with-a-blank-side", "앞 {{img::/교실}}{{img::민아/}} 뒤", "앞  뒤"],
    ["non-tags-untouched", "{{img::민아}} {{img::민아/교실", "{{img::민아}} {{img::민아/교실"],
    ["other-braces-untouched", "{{user}}\n\n{{char}}", "{{user}}\n\n{{char}}"],
    ["empty", "", ""],
  ])("%s", (_id, text, expected) => {
    expect(stripMediaTags(text)).toBe(expected);
  });

  it("returns tagless text byte for byte", () => {
    const text = "  첫 줄  \n\n\n\t둘째 줄\r\n\n";
    expect(stripMediaTags(text)).toBe(text);
  });
});

const IMAGES: MediaTagImages = { [MINA_CLASSROOM]: { url: "https://cdn/a.webp", width: 768, height: 1024 } };

describe("dropUnresolvedMediaTags", () => {
  it("keeps id tags that the map resolves and drops the rest like a deleted tag", () => {
    expect(dropUnresolvedMediaTags(`앞\n\n${tag(MINA_CLASSROOM)}\n\n${tag(UNKNOWN)}\n\n뒤`, IMAGES)).toBe(
      `앞\n\n${tag(MINA_CLASSROOM)}\n\n뒤`,
    );
  });

  it("leaves name-form tags and other braces as written", () => {
    const text = "{{img:: 민아 / 교실 }} {{user}}";
    expect(dropUnresolvedMediaTags(text, IMAGES)).toBe(text);
  });
});

describe("splitMediaTagText", () => {
  it("returns the text alone when there is no tag", () => {
    expect(splitMediaTagText("한 줄\n\n둘째", IMAGES)).toEqual([{ kind: "text", text: "한 줄\n\n둘째" }]);
  });

  it("splits around an image and trims the line breaks that framed the tag", () => {
    expect(splitMediaTagText(`앞 문단\n\n${tag(MINA_CLASSROOM)}\n\n뒤 문단`, IMAGES)).toEqual([
      { kind: "text", text: "앞 문단" },
      { kind: "image", cellId: MINA_CLASSROOM },
      { kind: "text", text: "뒤 문단" },
    ]);
  });

  it("splits a sentence around a mid-line tag", () => {
    expect(splitMediaTagText(`앞 ${tag(MINA_CLASSROOM.toUpperCase())} 뒤`, IMAGES)).toEqual([
      { kind: "text", text: "앞 " },
      { kind: "image", cellId: MINA_CLASSROOM },
      { kind: "text", text: " 뒤" },
    ]);
  });

  it("leaves a blank where the map has no image for the cell", () => {
    expect(splitMediaTagText(`앞\n\n${tag(UNKNOWN)}\n\n뒤`, IMAGES)).toEqual([{ kind: "text", text: "앞\n\n뒤" }]);
  });
});
