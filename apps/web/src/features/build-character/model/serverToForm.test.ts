import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { serverToForm } from "./serverToForm";

type CharacterDraftResponse = components["schemas"]["CharacterDraftResponse"];

function baseDraftResponse(): CharacterDraftResponse {
  return {
    id: "content-1",
    type: "character",
    name: "루나",
    oneLiner: "달빛 마법사",
    thumbnailAssetId: "asset-thumbnail",
    intro: "안녕, 나는 루나야.",
    exampleDialogues: [{ id: "dlg-1", userLine: "안녕?", characterLine: "반가워!" }],
    characterPrompt: "너는 상냥한 달빛 마법사다.",
    playguide: "존댓말을 쓰지 않아도 돼요.",
    situationalImages: [
      { id: "img-1", imageAssetId: "asset-1", triggerCondition: "웃을 때" },
      { id: "img-2", imageAssetId: null, triggerCondition: "화날 때" },
    ],
    description: "달빛 마법사 루나 이야기",
    genreId: "genre-fantasy",
    target: "all",
    hashtags: ["판타지"],
    visibility: "public",
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
      { id: "third", imageAssetId: null, triggerCondition: "third" },
      { id: "first", imageAssetId: null, triggerCondition: "first" },
      { id: "second", imageAssetId: null, triggerCondition: "second" },
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
});
