import { describe, expect, it } from "vitest";

import { toStoryImageArchiveView, type StoryImageArchiveItem } from "./toStoryImageArchiveView";

function item(overrides: Partial<StoryImageArchiveItem>): StoryImageArchiveItem {
  return {
    id: "cell-1",
    exposed: true,
    imageUrl: "https://s3.example/thumb.webp",
    width: 768,
    height: 1024,
    personName: "민아",
    sceneName: "옥상",
    unlockHint: "",
    ...overrides,
  };
}

describe("toStoryImageArchiveView", () => {
  it("shows a seen cell with its scene name and original aspect ratio", () => {
    const view = toStoryImageArchiveView([item({})]);

    expect(view.groups[0]?.tiles[0]).toEqual({
      kind: "unlocked",
      id: "cell-1",
      imageUrl: "https://s3.example/thumb.webp",
      sceneName: "옥상",
      aspectRatio: "768 / 1024",
      alt: "민아 · 옥상",
    });
  });

  it("hides the scene name of an unseen cell even when the server sends one, and keeps its hint", () => {
    const view = toStoryImageArchiveView([item({ exposed: false, sceneName: "옥상", unlockHint: " 밤에 옥상으로 " })]);

    // toEqual 은 남는 키를 허용하지 않으므로 장면 이름이 새면 여기서 걸린다.
    expect(view.groups[0]?.tiles[0]).toEqual({
      kind: "locked",
      id: "cell-1",
      imageUrl: "https://s3.example/thumb.webp",
      hint: "밤에 옥상으로",
      aspectRatio: "768 / 1024",
      alt: "민아의 아직 보지 못한 그림",
    });
  });

  it.each([[""], ["   "]])("drops a blank hint so the screen shows the lock alone (%j)", (unlockHint) => {
    const view = toStoryImageArchiveView([item({ exposed: false, sceneName: "", unlockHint })]);

    expect(view.groups[0]?.tiles[0]).toMatchObject({ kind: "locked", hint: undefined });
  });

  it.each([
    [null, 1024],
    [768, undefined],
    [0, 1024],
  ])("falls back to the fixed frame when the size is unknown (%s × %s)", (width, height) => {
    const view = toStoryImageArchiveView([item({ width, height })]);

    expect(view.groups[0]?.tiles[0]?.aspectRatio).toBeUndefined();
  });

  it("groups consecutive cells of the same person in server order and counts what was seen", () => {
    const view = toStoryImageArchiveView([
      item({ id: "a", personName: "민아" }),
      item({ id: "b", personName: "민아", exposed: false, sceneName: "" }),
      item({ id: "c", personName: "서준" }),
      item({ id: "d", personName: "민아" }),
    ]);

    expect(view.groups.map((group) => [group.personName, group.tiles.map((tile) => tile.id)])).toEqual([
      ["민아", ["a", "b"]],
      ["서준", ["c"]],
      ["민아", ["d"]],
    ]);
    expect([view.unlockedCount, view.totalCount]).toEqual([3, 4]);
  });

  it("returns no groups for a story without cells", () => {
    expect(toStoryImageArchiveView([])).toEqual({ groups: [], unlockedCount: 0, totalCount: 0 });
  });
});
