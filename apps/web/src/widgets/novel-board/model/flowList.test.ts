import { describe, expect, it } from "vitest";

import { testBatch, testCharacter, testEpisode, testModel } from "./boardTestModel";
import { toFlowListCharacters, toFlowListSections } from "./flowList";

describe("toFlowListSections", () => {
  it("묶음 번호 순, 묶음 안은 화 번호 순이고 입력 순서와 무관하다", () => {
    const model = testModel({
      batches: [testBatch("b2", 2), testBatch("b1", 1)],
      episodes: [testEpisode("e3", "b2", 3), testEpisode("e2", "b1", 2), testEpisode("e1", "b1", 1)],
    });

    const sections = toFlowListSections(model);

    expect(sections.map((section) => section.label)).toEqual(["묶음 1 · 1화", "묶음 2 · 2화"]);
    expect(sections.map((section) => section.episodes.map((episode) => episode.episodeId))).toEqual([["e1", "e2"], ["e3"]]);
  });

  it("화가 없는 묶음은 덩어리를 만들지 않고, 목록에 없는 묶음의 화는 맨 뒤로 모은다", () => {
    const model = testModel({
      batches: [testBatch("b1", 1), testBatch("empty", 2)],
      episodes: [testEpisode("lost", "gone", 5), testEpisode("e1", "b1", 1)],
    });

    const sections = toFlowListSections(model);

    expect(sections.map((section) => section.key)).toEqual(["b1", "orphans"]);
    expect(sections[1]?.episodes.map((episode) => episode.episodeId)).toEqual(["lost"]);
  });
});

describe("toFlowListCharacters", () => {
  it("처음 나온 화 순이고, 지금 없는 화에만 나온 인물은 뒤로 가며 나온 화 수는 지금 있는 화만 센다", () => {
    const model = testModel({
      batches: [testBatch("b1", 1)],
      episodes: [testEpisode("e1", "b1", 1), testEpisode("e2", "b1", 2)],
      characters: [testCharacter("late", ["e2"]), testCharacter("ghost", ["gone"]), testCharacter("early", ["e1", "e2", "gone"])],
    });

    const characters = toFlowListCharacters(model);

    expect(characters.map((character) => character.characterId)).toEqual(["early", "late", "ghost"]);
    expect(characters.map((character) => character.appearanceCount)).toEqual([2, 1, 0]);
  });
});
