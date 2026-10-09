import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { serverToForm } from "./serverToForm";

type CharacterDraftResponse = components["schemas"]["CharacterDraftResponse"];

function baseDraftResponse(): CharacterDraftResponse {
  return {
    id: "content-1",
    contentVersionId: "version-1",
    type: "character",
    name: "루나",
    oneLiner: "달빛 마법사",
    thumbnailAssetId: "asset-thumbnail",
    thumbnailUrl: "https://example.com/asset-thumbnail.webp",
    intro: "안녕, 나는 루나야.",
    exampleDialogues: [{ id: "dlg-1", userLine: "안녕?", characterLine: "반가워!" }],
    characterPrompt: "너는 상냥한 달빛 마법사다.",
    playguide: "존댓말을 쓰지 않아도 돼요.",
    defaultUserName: "",
    situationalImages: [
      { id: "img-1", imageAssetId: "asset-1", imageUrl: "https://example.test/asset-1_thumb.webp", triggerCondition: "웃을 때" },
      { id: "img-2", imageAssetId: null, imageUrl: null, triggerCondition: "화날 때" },
    ],
    description: "달빛 마법사 루나 이야기",
    genreId: "genre-fantasy",
    target: "all",
    hashtags: ["판타지"],
    visibility: "public",
    novelPermission: "forbidden",
  };
}

describe("serverToForm", () => {
  it("maps a CharacterDraftResponse into form defaultValues", () => {
    expect(serverToForm(baseDraftResponse())).toEqual({
      profile: { name: "루나", oneLiner: "달빛 마법사", image: { assetId: "asset-thumbnail" } },
      intro: {
        firstMessage: "안녕, 나는 루나야.",
        exampleDialogues: [{ id: "dlg-1", userLine: "안녕?", characterLine: "반가워!" }],
        playGuide: "존댓말을 쓰지 않아도 돼요.",
        defaultUserName: "",
      },
      prompt: { characterPrompt: "너는 상냥한 달빛 마법사다." },
      situationalImages: [
        { id: "img-1", image: { assetId: "asset-1" }, situationDescription: "웃을 때" },
        { id: "img-2", image: null, situationDescription: "화날 때" },
      ],
      registration: {
        description: "달빛 마법사 루나 이야기",
        genre: "genre-fantasy",
        target: "all",
        hashtags: ["판타지"],
        visibility: "public",
        novelPermission: "forbidden",
      },
    });
  });

  it("maps a null thumbnail and playguide back to a null image / unset play guide", () => {
    const data = baseDraftResponse();
    data.thumbnailAssetId = null;
    data.playguide = null;

    const form = serverToForm(data);

    expect(form.profile.image).toBeNull();
    expect(form.intro.playGuide).toBeUndefined();
  });

  it("restores an unselected draft's null genre/target as-is", () => {
    const data = baseDraftResponse();
    data.genreId = null;
    data.target = null;

    const form = serverToForm(data);

    expect(form.registration.genre).toBeNull();
    expect(form.registration.target).toBeNull();
  });

  it("keeps situationalImages in the response's order when restoring the array (no explicit order field on the wire)", () => {
    const data = baseDraftResponse();
    data.situationalImages = [
      { id: "third", imageAssetId: null, imageUrl: null, triggerCondition: "third" },
      { id: "first", imageAssetId: null, imageUrl: null, triggerCondition: "first" },
      { id: "second", imageAssetId: null, imageUrl: null, triggerCondition: "second" },
    ];

    const form = serverToForm(data);

    expect(form.situationalImages.map((item) => item.id)).toEqual(["third", "first", "second"]);
  });

  it("round-trips formToServer(serverToForm(response)) back to the same id/triggerCondition order", () => {
    const response = baseDraftResponse();

    const payload = formToServer(serverToForm(response));

    expect(payload.situationalImages).toEqual([
      { id: "img-1", triggerCondition: "웃을 때" },
      { id: "img-2", triggerCondition: "화날 때" },
    ]);
    expect(payload.name).toBe(response.name);
    expect(payload.genreId).toBe(response.genreId);
  });

  it("round-trips the default user name", () => {
    const response = { ...baseDraftResponse(), defaultUserName: "조수" };

    expect(formToServer(serverToForm(response)).defaultUserName).toBe("조수");
  });

  it("keeps a default user name typed with surrounding spaces the same after a save and reload", () => {
    const form = serverToForm(baseDraftResponse());
    form.intro.defaultUserName = " 조수 ";
    const saved = formToServer(form).defaultUserName;
    expect(saved).toBe("조수");

    const reloaded = serverToForm({ ...baseDraftResponse(), defaultUserName: saved ?? "" });

    expect(reloaded.intro.defaultUserName).toBe("조수");
    expect(formToServer(reloaded).defaultUserName).toBe("조수");
  });

  // 이 칸이 생기기 전 서버의 응답에는 키가 없다. 폼 값이 undefined 면 입력칸이 비제어로 시작하고 검사 함수가 던진다.
  it("treats a response without the default user name as an empty one", () => {
    const oldResponse: Partial<CharacterDraftResponse> = baseDraftResponse();
    delete oldResponse.defaultUserName;

    const form = serverToForm(oldResponse as CharacterDraftResponse);

    expect(form.intro.defaultUserName).toBe("");
    expect(formToServer(form).defaultUserName).toBe("");
  });

  it.each(["forbidden", "private", "public"] as const)("round-trips the novel permission %s", (novelPermission) => {
    const response = { ...baseDraftResponse(), novelPermission };

    expect(formToServer(serverToForm(response)).novelPermission).toBe(novelPermission);
  });

  // 이 칸이 생기기 전 서버의 응답에는 키가 없다. 새 작품과 같은 기본값으로 채운다.
  it("treats a response without the novel permission as the new-work default", () => {
    const oldResponse: Partial<CharacterDraftResponse> = baseDraftResponse();
    delete oldResponse.novelPermission;

    const form = serverToForm(oldResponse as CharacterDraftResponse);

    expect(form.registration.novelPermission).toBe("private");
  });
});
