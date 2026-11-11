import { describe, expect, it } from "vitest";

import { createCharacterMemoSchema, createCharacterNameSchema } from "./characterForm";
import { memoFormToServer, nameFormToServer } from "./formToServer";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 스키마는 검사만, 공백 걷기는 변환이 한다.
describe("nameFormToServer", () => {
  const schema = createCharacterNameSchema(5);

  it("sends only the trimmed name", () => {
    expect(nameFormToServer(schema.parse({ name: "  도희  " }))).toEqual({ name: "도희" });
  });
});

describe("memoFormToServer", () => {
  const schema = createCharacterMemoSchema(30);

  it("sends only the trimmed memo", () => {
    expect(memoFormToServer(schema.parse({ memo: "\n 야간 점원 \n" }))).toEqual({ memo: "야간 점원" });
  });

  it("turns a whitespace-only memo into an empty one, which clears it", () => {
    expect(memoFormToServer(schema.parse({ memo: "   " }))).toEqual({ memo: "" });
  });
});
