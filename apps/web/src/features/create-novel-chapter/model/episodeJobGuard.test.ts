import { describe, expect, it } from "vitest";

import type { NovelEpisodeOutlineView } from "@/entities/novel";

import { toEpisodeJobRefusal } from "./episodeJobGuard";

function view(extra: Partial<NovelEpisodeOutlineView> = {}): NovelEpisodeOutlineView {
  return {
    revision: 1,
    source: "generate",
    model: "gemini",
    approvedAt: "2026-10-24T00:00:00Z",
    createdAt: "2026-10-24T00:00:00Z",
    stale: false,
    scenes: [],
    ...extra,
  };
}

// 작업 줄의 다시 시도는 화 화면의 막기를 거치지 않는다 — 확인 창 앞에서 같은 이유로 멈춰야 한다.
describe("장면 구성안·원고 확인 앞 멈춤", () => {
  it("그 화를 고치는 중이면 둘 다 멈춘다", () => {
    expect(toEpisodeJobRefusal("episodeOutline", { approved: view(), draft: null }, true)).toBe(
      "고친 장면 구성안을 먼저 저장하거나 되돌려주세요.",
    );
    expect(toEpisodeJobRefusal("outlineChapter", { approved: view(), draft: null }, true)).toBe(
      "고친 장면 구성안을 먼저 저장하고 승인해주세요.",
    );
  });

  it("원고는 승인하지 않은 새 초안·승인본 없음·낡은 승인본이면 멈춘다", () => {
    expect(toEpisodeJobRefusal("outlineChapter", { approved: view(), draft: view({ revision: 2, approvedAt: null }) }, false)).toBe(
      "승인하지 않은 새 장면 구성안이 있어요. 승인한 뒤 원고를 쓸 수 있어요.",
    );
    expect(toEpisodeJobRefusal("outlineChapter", { approved: null, draft: null }, false)).toBe(
      "장면 구성안을 승인한 뒤 원고를 쓸 수 있어요.",
    );
    expect(toEpisodeJobRefusal("outlineChapter", { approved: view({ stale: true }), draft: null }, false)).toBe(
      "장면 구성안이 낡았어요. 다시 만들어 승인한 뒤 원고를 쓸 수 있어요.",
    );
  });

  it("막을 것이 없으면 진행한다(장면 구성안은 초안이 있어도 다시 만들 수 있다)", () => {
    expect(toEpisodeJobRefusal("outlineChapter", { approved: view(), draft: null }, false)).toBeUndefined();
    expect(toEpisodeJobRefusal("episodeOutline", { approved: null, draft: view({ approvedAt: null }) }, false)).toBeUndefined();
  });
});
