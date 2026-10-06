import { describe, expect, it } from "vitest";

import { MAX_BOARD_LAYOUT_BYTES, buildBoardLayoutPayload } from "./boardLayoutPayload";
import type { BoardModel, CharacterNode } from "./boardNode";
import { layoutBoard } from "./layoutBoard";

const model: BoardModel = {
  batches: [{ id: "b1", ordinal: 1 }],
  episodes: [{ id: "e1", batchId: "b1", ordinal: 1 }],
  characters: [{ id: "c1", episodeIds: ["e1"] }],
  hasNotes: true,
};

describe("buildBoardLayoutPayload", () => {
  it("keeps only the keys of nodes on the board, dropping derived batch frames and stale saved keys", () => {
    const { nodes } = layoutBoard(model, {
      version: 1,
      positions: { "episode:e1": { x: 10, y: 20 }, "character:merged-away": { x: 1, y: 1 } },
    });
    const payload = buildBoardLayoutPayload(nodes, undefined);
    expect(payload).not.toBeNull();
    expect(Object.keys(payload?.positions ?? {}).sort()).toEqual(["character:c1", "episode:e1", "notes"]);
    expect(payload?.positions["episode:e1"]).toEqual({ x: 10, y: 20 });
    expect(payload?.version).toBe(1);
    expect(payload && "viewport" in payload).toBe(false);
  });

  it("rounds positions and carries the viewport as is", () => {
    const { nodes } = layoutBoard(model, { version: 1, positions: { "episode:e1": { x: 10.4, y: -20.6 } } });
    const viewport = { x: 12.5, y: -3.25, zoom: 0.75 };
    const payload = buildBoardLayoutPayload(nodes, viewport);
    expect(payload?.positions["episode:e1"]).toEqual({ x: 10, y: -21 });
    expect(payload?.viewport).toEqual(viewport);
  });

  it("round-trips: laying out again from the payload reproduces the same positions", () => {
    const first = layoutBoard(model, { version: 1, positions: { "character:c1": { x: 700, y: 300 } } });
    const payload = buildBoardLayoutPayload(first.nodes, undefined);
    if (!payload) throw new Error("payload too large");
    expect(layoutBoard(model, payload).nodes).toEqual(first.nodes);
  });

  it("returns null instead of a body over the size limit", () => {
    const longId = "x".repeat(200);
    const characters: CharacterNode[] = Array.from({ length: 400 }, (_, index) => ({
      id: `character:${longId}${index}`,
      type: "character",
      position: { x: index, y: index },
      data: { characterId: `${longId}${index}` },
    }));
    expect(JSON.stringify({ version: 1, positions: characters }).length).toBeGreaterThan(MAX_BOARD_LAYOUT_BYTES);
    expect(buildBoardLayoutPayload(characters, undefined)).toBeNull();
  });
});
