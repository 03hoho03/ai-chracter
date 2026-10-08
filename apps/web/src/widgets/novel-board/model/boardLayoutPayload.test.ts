import { describe, expect, it } from "vitest";

import { buildBoardLayoutPayload } from "./boardLayoutPayload";
import type { BoardModel, CharacterNode } from "./boardNode";
import { testBatch, testCharacter, testEpisode, testModel } from "./boardTestModel";
import { layoutBoard } from "./layoutBoard";

const MAX_BYTES = 65_536;

const model: BoardModel = testModel({
  batches: [testBatch("b1", 1)],
  episodes: [testEpisode("e1", "b1", 1)],
  characters: [testCharacter("c1", ["e1"])],
});

describe("buildBoardLayoutPayload", () => {
  it("keeps only the keys of nodes on the board, dropping derived batch frames and stale saved keys", () => {
    const { nodes } = layoutBoard(model, {
      version: 1,
      viewport: null,
      positions: { "episode:e1": { x: 10, y: 20 }, "character:merged-away": { x: 1, y: 1 } },
    });
    const payload = buildBoardLayoutPayload(nodes, null, MAX_BYTES);
    expect(payload).not.toBeNull();
    expect(Object.keys(payload?.positions ?? {}).sort()).toEqual(["character:c1", "episode:e1", "notes"]);
    expect(payload?.positions["episode:e1"]).toEqual({ x: 10, y: 20 });
    expect(payload?.version).toBe(1);
  });

  it("always sends the viewport key, as null when the view is unknown, because the server rejects a missing key", () => {
    const { nodes } = layoutBoard(model, undefined);
    const payload = buildBoardLayoutPayload(nodes, null, MAX_BYTES);
    expect(payload).toHaveProperty("viewport", null);
    expect(JSON.stringify(payload)).toContain('"viewport":null');
  });

  it("rounds positions and carries the viewport as is", () => {
    const { nodes } = layoutBoard(model, {
      version: 1,
      viewport: null,
      positions: { "episode:e1": { x: 10.4, y: -20.6 } },
    });
    const viewport = { x: 12.5, y: -3.25, zoom: 0.75 };
    const payload = buildBoardLayoutPayload(nodes, viewport, MAX_BYTES);
    expect(payload?.positions["episode:e1"]).toEqual({ x: 10, y: -21 });
    expect(payload?.viewport).toEqual(viewport);
  });

  it("round-trips: laying out again from the payload reproduces the same positions", () => {
    const first = layoutBoard(model, { version: 1, viewport: null, positions: { "character:c1": { x: 700, y: 300 } } });
    const payload = buildBoardLayoutPayload(first.nodes, null, MAX_BYTES);
    if (!payload) throw new Error("payload too large");
    expect(layoutBoard(model, payload).nodes).toEqual(first.nodes);
  });

  it("returns null instead of a body over the limit the detail response gives", () => {
    const characters: CharacterNode[] = Array.from({ length: 50 }, (_, index) => ({
      id: `character:${"x".repeat(40)}${index}`,
      type: "character",
      position: { x: index, y: index },
      data: { characterId: `${index}`, name: "", memo: "", appearanceCount: 0 },
    }));
    const body = buildBoardLayoutPayload(characters, null, MAX_BYTES);
    if (!body) throw new Error("unexpected null");
    const size = JSON.stringify(body).length;
    expect(buildBoardLayoutPayload(characters, null, size)).toEqual(body);
    expect(buildBoardLayoutPayload(characters, null, size - 1)).toBeNull();
  });
});
