import { describe, expect, it } from "vitest";

import { createAuthorNoteSchema, createEpisodeTitleSchema } from "./episodeSchema";
import { authorNoteFormToServer, episodeTitleFormToServer } from "./formToServer";

// 화면 제출과 같은 경로(스키마 파싱 → 본문 변환)로 확인한다 — 스키마는 검사만, 공백 걷기는 변환이 한다.
describe("episodeTitleFormToServer", () => {
  const schema = createEpisodeTitleSchema(10);

  it("sends only the trimmed title", () => {
    expect(episodeTitleFormToServer(schema.parse({ title: "  첫 만남 " }))).toEqual({ title: "첫 만남" });
  });
});

describe("authorNoteFormToServer", () => {
  const schema = createAuthorNoteSchema(20);

  it("sends only the trimmed author note", () => {
    expect(authorNoteFormToServer(schema.parse({ authorNote: "\n 고마워요 \n" }))).toEqual({ authorNote: "고마워요" });
  });

  it("turns a whitespace-only note into an empty one, which clears it", () => {
    expect(authorNoteFormToServer(schema.parse({ authorNote: "  \n " }))).toEqual({ authorNote: "" });
  });
});
