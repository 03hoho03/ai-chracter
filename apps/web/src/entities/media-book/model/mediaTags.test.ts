// 정규화·삭제 표는 서버 테스트 `apps/api/tests/test_media_tags.py` 와 함께 읽는 JSON 하나다(`mediaTagCases.ts` 가
// 편다) — 빌더 미리보기의 첫 메시지는 이 구현으로, 실채팅의 첫 메시지는 서버 구현으로 정규화되므로 둘이 갈라지면
// 같은 글이 다르게 보인다. 표에 없는 사례만 여기 적는다.
import { describe, expect, it } from "vitest";

import {
  dropUnresolvedMediaTags,
  hasMediaTag,
  normalizeMediaTags,
  renameMediaTagName,
  splitMediaTagText,
  stripMediaTags,
  type MediaTagImages,
} from "./mediaTags";
import { loadMediaTagCases } from "./mediaTagCases";

const {
  cells: CELLS,
  minaClassroom: MINA_CLASSROOM,
  normalizeCases: NORMALIZE_CASES,
  stripCases: STRIP_CASES,
} = loadMediaTagCases();

const UNKNOWN = "bbbbbbbb-0000-0000-0000-000000000009";
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
  it.each(STRIP_CASES)("%s", (_id, text, expected) => {
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

describe("renameMediaTagName", () => {
  it("renames only the tag whose person is exactly the old name, not a name that contains it", () => {
    const text = "{{img::리아/기쁨}} 그리고 {{img::마리아/기쁨}} — 리아가 웃었다";

    expect(renameMediaTagName(text, "person", "리아", "레아")).toBe(
      "{{img::레아/기쁨}} 그리고 {{img::마리아/기쁨}} — 리아가 웃었다",
    );
  });

  it("renames the scene side without touching a person with the same name", () => {
    const text = "{{img::기쁨/기쁨}}";

    expect(renameMediaTagName(text, "scene", "기쁨", "환희")).toBe("{{img::기쁨/환희}}");
  });

  it("matches names after trimming and NFC, writing the normalized new name", () => {
    const decomposed = "리아".normalize("NFD");

    expect(renameMediaTagName(`{{img:: ${decomposed} /기쁨}}`, "person", "리아", " 레아 ")).toBe("{{img::레아/기쁨}}");
  });

  it("leaves id-form tags, other braces and tags with two slashes alone", () => {
    const text = "{{img::00000000-0000-4000-8000-000000000021}} {{user}} {{img::리아/기쁨/2}}";

    expect(renameMediaTagName(text, "person", "리아", "레아")).toBe(text);
  });
});

describe("hasMediaTag", () => {
  it("detects either tag form", () => {
    expect(hasMediaTag("x {{img::00000000-0000-4000-8000-000000000021}}")).toBe(true);
    expect(hasMediaTag("x {{user}}")).toBe(false);
    expect(hasMediaTag(undefined)).toBe(false);
  });
});
