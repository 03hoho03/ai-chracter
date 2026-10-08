import { describe, expect, it } from "vitest";

import {
  BATCH_GAP,
  CHARACTER_GAP,
  CHARACTER_NODE_HEIGHT,
  EPISODE_GAP,
  EPISODE_NODE_HEIGHT,
  type BoardModel,
  type BoardNode,
} from "./boardNode";
import { testBatch, testCharacter, testEpisode, testModel } from "./boardTestModel";
import { buildCharacterEdges, layoutBoard } from "./layoutBoard";

const model: BoardModel = testModel({
  batches: [testBatch("b2", 2), testBatch("b1", 1)],
  episodes: [testEpisode("e3", "b2", 3), testEpisode("e1", "b1", 1), testEpisode("e2", "b1", 2)],
  characters: [
    testCharacter("c-late", ["e3"]),
    testCharacter("c-b", ["e2", "e1"]),
    testCharacter("c-a", ["e1"]),
    testCharacter("c-gone", ["deleted-episode"]),
  ],
  notes: "편의점 야간 점원",
});

function positionOf(nodes: BoardNode[], id: string) {
  return nodes.find((node) => node.id === id)?.position;
}

describe("layoutBoard", () => {
  it("returns the same nodes and edges for the same input regardless of input array order", () => {
    const shuffled: BoardModel = {
      ...model,
      batches: [...model.batches].reverse(),
      episodes: [...model.episodes].reverse(),
      characters: [...model.characters].reverse(),
    };
    expect(layoutBoard(shuffled, undefined)).toEqual(layoutBoard(model, undefined));
  });

  it("stacks episodes in one column in batch then episode order, with a wider gap between batches", () => {
    const { nodes } = layoutBoard(model, undefined);
    const e1 = positionOf(nodes, "episode:e1");
    const e2 = positionOf(nodes, "episode:e2");
    const e3 = positionOf(nodes, "episode:e3");
    expect(e1).toEqual({ x: 0, y: 0 });
    expect(e2).toEqual({ x: 0, y: EPISODE_NODE_HEIGHT + EPISODE_GAP });
    expect(e3).toEqual({ x: 0, y: 2 * EPISODE_NODE_HEIGHT + EPISODE_GAP + BATCH_GAP });
  });

  it("links each episode to the next one in reading order, bottom of one card to the top of the next", () => {
    const { edges } = layoutBoard(model, undefined);
    expect(edges.map((edge) => [edge.source, edge.target])).toEqual([
      ["episode:e1", "episode:e2"],
      ["episode:e2", "episode:e3"],
    ]);
    expect(edges.every((edge) => edge.sourceHandle === "next-out" && edge.targetHandle === "next-in")).toBe(true);
  });

  it("puts characters in a lane right of the episodes at the height of their first appearance", () => {
    const { nodes } = layoutBoard(model, undefined);
    const e1 = positionOf(nodes, "episode:e1");
    const e3 = positionOf(nodes, "episode:e3");
    const a = positionOf(nodes, "character:c-a");
    const b = positionOf(nodes, "character:c-b");
    const late = positionOf(nodes, "character:c-late");
    if (!e1 || !e3 || !a || !b || !late) throw new Error("missing node");

    expect(a.x).toBeGreaterThan(e1.x);
    expect(a.y).toBe(e1.y);
    // 같은 화에 처음 나온 인물은 겹치지 않게 아래로 밀린다(같은 높이에서는 id 순).
    expect(b).toEqual({ x: a.x, y: a.y + CHARACTER_NODE_HEIGHT + CHARACTER_GAP });
    expect(late).toEqual({ x: a.x, y: e3.y });
  });

  it("stacks characters whose episodes are all gone after the ones on the board", () => {
    const { nodes } = layoutBoard(model, undefined);
    const late = positionOf(nodes, "character:c-late");
    const gone = positionOf(nodes, "character:c-gone");
    if (!late || !gone) throw new Error("missing node");
    expect(gone.y).toBe(late.y + CHARACTER_NODE_HEIGHT + CHARACTER_GAP);
  });

  it("places the notes card top-left of the episode column", () => {
    const { nodes } = layoutBoard(model, undefined);
    const notes = positionOf(nodes, "notes");
    if (!notes) throw new Error("missing node");
    expect(notes.x).toBeLessThan(0);
    expect(notes.y).toBe(0);
  });

  it("always draws the notes card, even when the notes are empty, since it is the canvas entry for writing them", () => {
    const { nodes } = layoutBoard({ ...model, notes: "" }, undefined);
    expect(nodes.find((node) => node.type === "notes")?.data).toEqual({ notes: "" });
  });

  it("orders nodes notes, episodes in reading order, then characters by first appearance (the canvas tab order)", () => {
    const { nodes } = layoutBoard(model, null);
    expect(nodes.filter((node) => node.type !== "batchFrame").map((node) => node.id)).toEqual([
      "notes",
      "episode:e1",
      "episode:e2",
      "episode:e3",
      "character:c-a",
      "character:c-b",
      "character:c-late",
      "character:c-gone",
    ]);
  });

  it("carries the fields the cards draw in node data, so a memoized card redraws when one changes", () => {
    const titled: BoardModel = {
      ...model,
      episodes: model.episodes.map((episode) =>
        episode.id === "e1" ? { ...episode, title: "첫 손님", readState: { kind: "reading", percent: 42 } } : episode,
      ),
    };
    const { nodes } = layoutBoard(titled, undefined);
    expect(nodes.find((node) => node.id === "episode:e1")?.data).toMatchObject({
      episodeId: "e1",
      title: "첫 손님",
      readState: { kind: "reading", percent: 42 },
    });
    expect(nodes.find((node) => node.id === "character:c-b")?.data).toEqual({
      characterId: "c-b",
      name: "c-b",
      memo: "",
      appearanceCount: 2,
    });
    expect(nodes.find((node) => node.id === "character:c-gone")?.data).toMatchObject({ appearanceCount: 0 });
    expect(nodes.find((node) => node.id === "batch:b1")?.data).toEqual({ batchId: "b1", ordinal: 1, rangeLabel: "1화" });
  });

  it("lets saved positions override the automatic ones and ignores keys of nodes no longer on the board", () => {
    const { nodes } = layoutBoard(model, {
      version: 1,
      viewport: null,
      positions: {
        "episode:e2": { x: 500, y: -40 },
        "character:c-a": { x: 900, y: 900 },
        notes: { x: -1, y: -2 },
        "episode:deleted": { x: 1, y: 1 },
        "character:merged-away": { x: 2, y: 2 },
      },
    });
    expect(positionOf(nodes, "episode:e2")).toEqual({ x: 500, y: -40 });
    expect(positionOf(nodes, "character:c-a")).toEqual({ x: 900, y: 900 });
    expect(positionOf(nodes, "notes")).toEqual({ x: -1, y: -2 });
    expect(positionOf(nodes, "episode:e1")).toEqual({ x: 0, y: 0 });
    expect(nodes.some((node) => node.id === "episode:deleted" || node.id === "character:merged-away")).toBe(false);
  });

  it("keeps automatic character heights tied to the automatic episode layout, not to moved episodes", () => {
    const moved = layoutBoard(model, { version: 1, viewport: null, positions: { "episode:e3": { x: 0, y: 5000 } } });
    const fresh = layoutBoard(model, undefined);
    expect(positionOf(moved.nodes, "character:c-late")).toEqual(positionOf(fresh.nodes, "character:c-late"));
  });

  it("puts batch frames first so they draw behind the cards, and frames follow saved episode positions", () => {
    const { nodes } = layoutBoard(model, { version: 1, viewport: null, positions: { "episode:e3": { x: 300, y: 2000 } } });
    expect(nodes.slice(0, 2).map((node) => node.id)).toEqual(["batch:b1", "batch:b2"]);
    const frame = nodes.find((node) => node.id === "batch:b2");
    if (!frame) throw new Error("missing frame");
    expect(frame.position.x).toBeLessThan(300);
    expect(frame.position.y).toBeLessThan(2000);
  });
});

describe("buildCharacterEdges", () => {
  it("draws nothing when no character is chosen or the character is unknown", () => {
    expect(buildCharacterEdges(undefined, model)).toEqual([]);
    expect(buildCharacterEdges("nobody", model)).toEqual([]);
  });

  it("links the chosen character only to episodes still on the board", () => {
    expect(buildCharacterEdges("c-b", model).map((edge) => [edge.source, edge.target])).toEqual([
      ["character:c-b", "episode:e2"],
      ["character:c-b", "episode:e1"],
    ]);
    expect(buildCharacterEdges("c-gone", model)).toEqual([]);
  });

  it("plugs character lines into the side handles so they do not land on the top of episode cards", () => {
    const edges = buildCharacterEdges("c-a", model);
    expect(edges.map((edge) => [edge.sourceHandle, edge.targetHandle])).toEqual([["appears-out", "appears-in"]]);
  });

  it("names character lines in Korean (the library default is an English key dump)", () => {
    expect(buildCharacterEdges("c-b", model).map((edge) => edge.ariaLabel)).toEqual(["인물 c-b · 2화", "인물 c-b · 1화"]);
  });
});

describe("edge accessible names", () => {
  it("names next-episode lines by episode numbers and describes every line's role in Korean", () => {
    const { edges } = layoutBoard(model, null);
    expect(edges.map((edge) => edge.ariaLabel)).toEqual(["1화 → 2화", "2화 → 3화"]);
    expect(edges.every((edge) => edge.domAttributes?.["aria-roledescription"] === "선")).toBe(true);
  });
});
