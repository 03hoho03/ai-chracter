import { describe, expect, it } from "vitest";

import type { ContentDraftPayload, NovelPermission } from "@/entities/content";

import { createNovelPermissionSync } from "./novelPermissionSync";

/** 빌더가 보내는 캐릭터 초안 저장 모양. 허락 칸 말고는 이 기록이 보지 않는다. */
function payloadWith(novelPermission: NovelPermission): ContentDraftPayload {
  return {
    name: "루나",
    oneLiner: "",
    thumbnailAssetId: null,
    intro: "",
    exampleDialogues: [],
    characterPrompt: "",
    playguide: null,
    situationalImages: [],
    description: "",
    genreId: null,
    target: null,
    hashtags: [],
    visibility: "private",
    novelPermission,
  };
}

describe("createNovelPermissionSync", () => {
  it("leaves the field out while the form still holds the value it was loaded with", () => {
    const sync = createNovelPermissionSync("private");

    const sent = sync.prepare(payloadWith("private"));

    expect("novelPermission" in sent).toBe(false);
    // 다른 칸은 그대로 간다.
    expect(sent.visibility).toBe("private");
  });

  it("sends the field once the author picks a different value in the builder", () => {
    const sync = createNovelPermissionSync("private");

    expect(sync.prepare(payloadWith("forbidden")).novelPermission).toBe("forbidden");
  });

  // 빌더가 열려 있는 동안 작품 상세에서 값을 바꾼 경우: 폼은 여전히 보냈던 값을 들고 있다. 다른 칸을 고친 저장이 그 값을
  // 다시 보내면 상세에서 바꾼 값이 되돌려진다.
  it("does not resend a value it already sent, so a later change made elsewhere survives the next autosave", () => {
    const sync = createNovelPermissionSync("private");
    sync.prepare(payloadWith("forbidden"));

    const next = sync.prepare(payloadWith("forbidden"));

    expect("novelPermission" in next).toBe(false);
  });

  // 자동저장은 앞 저장의 응답을 기다리지 않는다. 응답 전에 원래 값으로 되돌린 저장이 칸을 빼면 서버에는 앞 저장의 값이 남는다.
  it("sends the original value when the author switches back before the previous save answers", () => {
    const sync = createNovelPermissionSync("private");
    sync.prepare(payloadWith("forbidden"));

    expect(sync.prepare(payloadWith("private")).novelPermission).toBe("private");
  });

  it("resends the value after a save that carried it fails", () => {
    const sync = createNovelPermissionSync("private");
    const failed = sync.prepare(payloadWith("public"));
    sync.fail(failed);

    expect(sync.prepare(payloadWith("public")).novelPermission).toBe("public");
  });

  // 칸을 뺀 저장은 서버의 그 칸을 건드리지 않았으니, 실패해도 다른 곳에서 바꾼 값을 덮을 이유가 없다.
  it("keeps leaving the field out after a failed save that did not carry it", () => {
    const sync = createNovelPermissionSync("private");
    sync.fail(sync.prepare(payloadWith("private")));

    expect("novelPermission" in sync.prepare(payloadWith("private"))).toBe(false);
  });

  // 칸을 모르는 옛 서버의 초안에는 값이 없다. 그때 폼이 채운 기본값은 실어 보내도 그 서버가 무시한다.
  it("sends the form value when the loaded draft had no value at all", () => {
    const sync = createNovelPermissionSync(undefined);

    expect(sync.prepare(payloadWith("private")).novelPermission).toBe("private");
  });
});
