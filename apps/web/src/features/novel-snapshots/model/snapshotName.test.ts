import { describe, expect, it } from "vitest";

import { createSnapshotNameSchema, toDefaultSnapshotName } from "./snapshotName";

describe("toDefaultSnapshotName", () => {
  it("names the version after the last episode, regardless of list order", () => {
    expect(toDefaultSnapshotName([3, 7, 5])).toBe("7화까지");
  });

  it("before the first episode", () => {
    expect(toDefaultSnapshotName([])).toBe("첫 화 전");
  });
});

describe("createSnapshotNameSchema", () => {
  const schema = createSnapshotNameSchema(5);

  it("rejects a blank name as the server does after trimming", () => {
    expect(schema.safeParse({ name: "   " }).success).toBe(false);
  });

  it("counts code points of the trimmed name against the limit", () => {
    expect(schema.safeParse({ name: "  다섯글자다  " }).success).toBe(true);
    expect(schema.safeParse({ name: "😀😀😀😀😀" }).success).toBe(true);
    expect(schema.safeParse({ name: "여섯글자이다" }).success).toBe(false);
  });
});
