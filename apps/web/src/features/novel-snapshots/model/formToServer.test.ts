import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { createSnapshotNameSchema } from "./snapshotName";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 스키마는 검사만, 공백 걷기는 변환이 한다.
describe("snapshot name body", () => {
  const schema = createSnapshotNameSchema(10);

  it("sends the trimmed name", () => {
    expect(formToServer(schema.parse({ name: "  3화까지 " }))).toEqual({ name: "3화까지" });
  });

  it("counts the limit without the surrounding spaces", () => {
    expect(formToServer(schema.parse({ name: ` ${"가".repeat(10)} ` }))).toEqual({ name: "가".repeat(10) });
  });
});
