import { describe, expect, it } from "vitest";

import { synopsisFormToServer, titleFormToServer } from "./formToServer";
import { createSynopsisFormSchema, createTitleFormSchema } from "./novelInfoSchema";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 스키마는 검사만, 공백 걷기는 변환이 한다.
describe("titleFormToServer", () => {
  const schema = createTitleFormSchema(5);

  it("sends only the trimmed title", () => {
    expect(titleFormToServer(schema.parse({ title: "  밤의 끝  " }))).toEqual({ title: "밤의 끝" });
  });
});

describe("synopsisFormToServer", () => {
  const schema = createSynopsisFormSchema(10);

  it("sends only the trimmed synopsis", () => {
    expect(synopsisFormToServer(schema.parse({ synopsis: "\n 짧은 소개 \n" }))).toEqual({ synopsis: "짧은 소개" });
  });

  it("turns a whitespace-only synopsis into an empty one, which clears it", () => {
    expect(synopsisFormToServer(schema.parse({ synopsis: "   " }))).toEqual({ synopsis: "" });
  });
});
