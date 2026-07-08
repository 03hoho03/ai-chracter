import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import type { CharacterBuilderFormValues } from "./schema";

function baseFormValues(): CharacterBuilderFormValues {
  return {
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
  };
}

describe("formToServer", () => {
  it("maps every tab into the CharacterDraftPayload shape", () => {
    expect(formToServer(baseFormValues())).toEqual({
      name: "루나",
      oneLiner: "달빛 마법사",
      thumbnailAssetId: "asset-thumbnail",
      intro: "안녕, 나는 루나야.",
      exampleDialogues: [{ id: "dlg-1", userLine: "안녕?", characterLine: "반가워!" }],
      characterPrompt: "너는 상냥한 달빛 마법사다.",
      playguide: "존댓말을 쓰지 않아도 돼요.",
      situationalImages: [
        { id: "img-1", triggerCondition: "웃을 때" },
        { id: "img-2", triggerCondition: "화날 때" },
      ],
      description: "달빛 마법사 루나 이야기",
      genreId: "genre-fantasy",
      target: "all",
      hashtags: ["판타지"],
      visibility: "public",
    });
  });

  it("maps a null profile image and an unset play guide to null", () => {
    const values = baseFormValues();
    values.profile.image = null;
    values.intro.playGuide = undefined;

    const payload = formToServer(values);

    expect(payload.thumbnailAssetId).toBeNull();
    expect(payload.playguide).toBeNull();
  });

  it("preserves situationalImages array order as the wire's implicit priority (no explicit order field)", () => {
    const values = baseFormValues();
    values.situationalImages = [
      { id: "third", image: null, situationDescription: "third" },
      { id: "first", image: null, situationDescription: "first" },
      { id: "second", image: null, situationDescription: "second" },
    ];

    const payload = formToServer(values);

    expect(payload.situationalImages.map((item) => item.id)).toEqual(["third", "first", "second"]);
    expect(payload.situationalImages[0]).toEqual({ id: "third", triggerCondition: "third" });
  });
});
