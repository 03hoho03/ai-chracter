import { describe, expect, it } from "vitest";

import { buildRegeneratePayload } from "./buildRegeneratePayload";

describe("buildRegeneratePayload", () => {
  it("builds a regenerate request for the given room", () => {
    expect(buildRegeneratePayload({ roomId: "room-1" })).toEqual({ kind: "regenerate", roomId: "room-1" });
  });
});
