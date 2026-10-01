import { describe, expect, it } from "vitest";

import { characterImageArchiveKeys } from "@/entities/character-image-archive";
import { storyImageArchiveKeys } from "@/entities/story-image-archive";

import { imageArchiveKeyToInvalidate } from "./imageArchiveKeyToInvalidate";

describe("imageArchiveKeyToInvalidate", () => {
  it("invalidates the character archive only when the reply carries a situational image", () => {
    const target = { contentType: "character", contentId: "char-1" } as const;

    expect(imageArchiveKeyToInvalidate(target, { imageId: "img-1" })).toEqual(characterImageArchiveKeys.list("char-1"));
    expect(imageArchiveKeyToInvalidate(target, { imageId: undefined })).toBeUndefined();
  });

  it("invalidates the story archive after every turn, with or without an image", () => {
    const target = { contentType: "story", contentId: "story-1" } as const;

    expect(imageArchiveKeyToInvalidate(target, { imageId: "cell-1" })).toEqual(storyImageArchiveKeys.list("story-1"));
    expect(imageArchiveKeyToInvalidate(target, { imageId: undefined })).toEqual(storyImageArchiveKeys.list("story-1"));
  });

  it("does nothing before the room is known", () => {
    expect(imageArchiveKeyToInvalidate(undefined, { imageId: "img-1" })).toBeUndefined();
  });
});
