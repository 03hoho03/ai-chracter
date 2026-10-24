import { describe, expect, it } from "vitest";

import type { NovelEpisodeOutlineView } from "@/entities/novel";

import {
  isSameAsSceneView,
  moveScene,
  removeScene,
  toggleFlashback,
  toSaveScenes,
  toSceneDrafts,
  toSceneMoveBlockedReason,
  toSceneProblems,
  toSceneRemoveBlockedReason,
  updateSceneText,
} from "./episodeScenes";

const view = {
  revision: 3,
  source: "generate",
  model: "gemini",
  approvedAt: null,
  createdAt: "2026-10-24T00:00:00Z",
  stale: false,
  scenes: [
    {
      id: "s1",
      title: "문 앞",
      summary: "규칙을 처음 듣는다.",
      purpose: "규칙 소개",
      characters: ["서진", "집사"],
      flashback: false,
      basis: [{ startMessageId: "m1", endMessageId: "m4" }],
    },
    {
      id: "s2",
      title: "회랑",
      summary: "탑의 소문.",
      purpose: "",
      characters: [],
      flashback: true,
      basis: [{ startMessageId: "m5", endMessageId: "m6" }],
    },
    {
      id: "s3",
      title: "저녁 식탁",
      summary: "계약 조건을 되묻는다.",
      purpose: "",
      characters: ["서진"],
      flashback: false,
      basis: [{ startMessageId: "m7", endMessageId: "m10" }],
    },
  ],
} satisfies NovelEpisodeOutlineView;

describe("장면 편집", () => {
  it("뷰를 그대로 편집 장면으로 편다", () => {
    const scenes = toSceneDrafts(view);
    expect(scenes.map((scene) => scene.localId)).toEqual(["s1", "s2", "s3"]);
    expect(isSameAsSceneView(scenes, view)).toBe(true);
  });

  it("글을 고치면 달라지고, 같은 글로 되돌리면 같다", () => {
    const scenes = toSceneDrafts(view);
    const edited = updateSceneText(scenes, "s2", { title: "긴 회랑", summary: "탑의 소문.", purpose: "" });
    expect(edited[1]?.title).toBe("긴 회랑");
    expect(isSameAsSceneView(edited, view)).toBe(false);
    expect(isSameAsSceneView(updateSceneText(edited, "s2", { title: "회랑", summary: "탑의 소문.", purpose: "" }), view)).toBe(true);
  });

  it("차례를 바꾸고, 맨 앞·맨 뒤는 더 옮기지 못한다", () => {
    const scenes = toSceneDrafts(view);
    expect(moveScene(scenes, "s3", -1).map((scene) => scene.id)).toEqual(["s1", "s3", "s2"]);
    expect(toSceneMoveBlockedReason(scenes, "s1", -1)).toBe("맨 앞 장면이에요.");
    expect(toSceneMoveBlockedReason(scenes, "s3", 1)).toBe("맨 뒤 장면이에요.");
    expect(toSceneMoveBlockedReason(scenes, "s2", 1)).toBeUndefined();
    expect(isSameAsSceneView(moveScene(scenes, "s3", -1), view)).toBe(false);
  });

  it("장면을 빼고, 하나 남으면 더 빼지 못한다", () => {
    const scenes = toSceneDrafts(view);
    expect(removeScene(scenes, "s2").map((scene) => scene.id)).toEqual(["s1", "s3"]);
    expect(toSceneRemoveBlockedReason(scenes)).toBeUndefined();
    expect(toSceneRemoveBlockedReason(removeScene(removeScene(scenes, "s2"), "s3"))).toBe(
      "장면 구성안에는 장면이 하나 이상 있어야 해요.",
    );
  });

  it("회상 표시를 켜고 끈다", () => {
    const scenes = toSceneDrafts(view);
    expect(toggleFlashback(scenes, "s1")[0]?.flashback).toBe(true);
    expect(toggleFlashback(scenes, "s2")[1]?.flashback).toBe(false);
    expect(isSameAsSceneView(toggleFlashback(toggleFlashback(scenes, "s1"), "s1"), view)).toBe(true);
  });

  it("저장 몸은 장면 id·근거·등장인물을 그대로 두고 글의 앞뒤 공백만 걷는다", () => {
    const scenes = updateSceneText(toSceneDrafts(view), "s1", { title: "  문 앞 ", summary: " 규칙을 처음 듣는다. ", purpose: " 소개 " });
    expect(toSaveScenes(removeScene(scenes, "s2"))).toEqual([
      {
        id: "s1",
        title: "문 앞",
        summary: "규칙을 처음 듣는다.",
        purpose: "소개",
        characters: ["서진", "집사"],
        flashback: false,
        basis: [{ startMessageId: "m1", endMessageId: "m4" }],
      },
      {
        id: "s3",
        title: "저녁 식탁",
        summary: "계약 조건을 되묻는다.",
        purpose: "",
        characters: ["서진"],
        flashback: false,
        basis: [{ startMessageId: "m7", endMessageId: "m10" }],
      },
    ]);
  });

  it("저장 전에 빈 제목·빈 내용·길이 초과를 장면 번호로 짚는다", () => {
    const scenes = toSceneDrafts(view);
    const empty = updateSceneText(scenes, "s2", { title: " ", summary: "", purpose: "" });
    expect(toSceneProblems(empty, { titleMaxLength: 100 })).toEqual([
      "장면 2 제목을 적어주세요.",
      "장면 2 내용을 적어주세요.",
    ]);
    const long = updateSceneText(scenes, "s1", { title: "가".repeat(11), summary: "나".repeat(1001), purpose: "다".repeat(301) });
    expect(toSceneProblems(long, { titleMaxLength: 10 })).toEqual([
      "장면 1 제목은 10자까지 쓸 수 있어요.",
      "장면 1 내용은 1,000자까지 쓸 수 있어요.",
      "장면 1 목적은 300자까지 쓸 수 있어요.",
    ]);
    expect(toSceneProblems(scenes, { titleMaxLength: 100 })).toEqual([]);
  });
});
