import { describe, expect, it } from "vitest";

import { createMemoryFormSchema } from "./schema";

const limits = { noteMaxLength: 1000, summaryMaxLength: 1500 };
const schema = createMemoryFormSchema(limits);

describe("createMemoryFormSchema", () => {
  // 서버 요청 스키마와 같은 규칙을 FE가 먼저 막는다 — 422 원문을 보이지 않고, 붙여넣기가 조용히 잘리지
  // 않게(입력칸에 maxLength를 두지 않는다).
  it("accepts both fields at their limits after trimming the surrounding whitespace", () => {
    const result = schema.safeParse({ note: `  ${"가".repeat(1000)}\n`, summary: ` ${"나".repeat(1500)} ` });
    expect(result.success).toBe(true);
    expect(result.data).toEqual({ note: "가".repeat(1000), summary: "나".repeat(1500) });
  });

  it("allows saving an empty note and an empty summary", () => {
    expect(schema.safeParse({ note: "   ", summary: "" }).data).toEqual({ note: "", summary: "" });
  });

  it.each([
    ["note", { note: "가".repeat(1001), summary: "" }],
    ["summary", { note: "", summary: "나".repeat(1501) }],
  ])("rejects a %s one character over the limit on that field only", (field, values) => {
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.path[0])).toEqual([field]);
  });

  it("takes the limits from the server response instead of a local copy", () => {
    const narrow = createMemoryFormSchema({ noteMaxLength: 3, summaryMaxLength: 5 });
    expect(narrow.safeParse({ note: "가나다", summary: "가나다라마" }).success).toBe(true);
    expect(narrow.safeParse({ note: "가나다라", summary: "" }).success).toBe(false);
  });
});
