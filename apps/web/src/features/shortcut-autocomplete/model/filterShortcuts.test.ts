import { describe, expect, it } from "vitest";

import type { Shortcut } from "@/entities/chat-room";
import { filterShortcuts } from "./filterShortcuts";

const shortcuts: Shortcut[] = [
  { id: "s1", name: "공격", description: "상대를 공격한다", prompt: "나는 상대를 향해 칼을 휘두른다." },
  { id: "s2", name: "인사", description: "가볍게 인사한다", prompt: "나는 손을 흔들며 인사한다." },
];

describe("filterShortcuts", () => {
  it("returns every shortcut when the query is empty", () => {
    expect(filterShortcuts("", shortcuts)).toEqual(shortcuts);
  });

  it("filters by name, case-insensitively", () => {
    expect(filterShortcuts("공격", shortcuts)).toEqual([shortcuts[0]]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(filterShortcuts("없는단축어", shortcuts)).toEqual([]);
  });
});
