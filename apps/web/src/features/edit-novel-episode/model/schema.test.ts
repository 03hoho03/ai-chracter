import { describe, expect, it } from "vitest";

import { createAuthorNoteSchema, createEpisodeTitleSchema, toEpisodeHeading } from "./schema";

describe("createEpisodeTitleSchema", () => {
  const schema = createEpisodeTitleSchema(4);

  it("rejects a blank title (clearing is a separate action) and counts trimmed code points", () => {
    expect(schema.safeParse({ title: "  " }).success).toBe(false);
    expect(schema.safeParse({ title: " 첫 손님 " }).success).toBe(true);
    expect(schema.safeParse({ title: "다섯 글자" }).success).toBe(false);
  });
});

describe("createAuthorNoteSchema", () => {
  it("accepts an empty note (deletes it) and caps the length", () => {
    const schema = createAuthorNoteSchema(3);
    expect(schema.safeParse({ authorNote: "" }).success).toBe(true);
    expect(schema.safeParse({ authorNote: "네 글자다" }).success).toBe(false);
  });
});

describe("toEpisodeHeading", () => {
  it("numbers the episode and adds the title when there is one", () => {
    expect(toEpisodeHeading({ ordinal: 4, title: "두 번째 계산" })).toBe("4화. 두 번째 계산");
    expect(toEpisodeHeading({ ordinal: 4, title: null })).toBe("4화");
  });
});
