import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { mediaBookPublishErrorMessage } from "./mediaBookPublishErrorMessage";
import type { MediaBookValues } from "./schema";

const MEDIA_BOOK: MediaBookValues = {
  people: [{ id: "p1", name: "민아" }],
  scenes: [{ id: "s1", name: "옥상" }],
  cells: [
    {
      id: "c1",
      personId: "p1",
      sceneId: "s1",
      imageAssetId: "a1",
      situationDescription: "",
      unlockHint: "",
      excludeFromChat: false,
    },
  ],
};

function imageUnavailable(cellId: unknown) {
  return new ApiErrorObject({
    status: 502,
    message: "bad gateway",
    detail: { code: "MEDIA_BOOK_IMAGE_UNAVAILABLE", cellId, message: "server text" },
  });
}

describe("mediaBookPublishErrorMessage", () => {
  it("names the cell whose picture could not be processed", () => {
    expect(mediaBookPublishErrorMessage(imageUnavailable("c1"), MEDIA_BOOK)).toBe(
      "미디어 북 '민아 / 옥상' 칸의 이미지를 처리하지 못해 발행이 멈췄어요. 잠시 뒤 다시 발행하고, 같은 일이 반복되면 그 칸 이미지를 다시 올려 주세요.",
    );
  });

  it("still explains the failure when the cell is no longer in the form", () => {
    expect(mediaBookPublishErrorMessage(imageUnavailable("gone"), MEDIA_BOOK)).toMatch(/^미디어 북 칸 이미지 하나를 처리하지 못해/);
  });

  it("leaves other publish failures to the default message", () => {
    expect(
      mediaBookPublishErrorMessage(new ApiErrorObject({ status: 502, message: "x", detail: "Bad Gateway" }), MEDIA_BOOK),
    ).toBeUndefined();
    expect(
      mediaBookPublishErrorMessage(
        new ApiErrorObject({ status: 502, message: "x", detail: { code: "OTHER", cellId: "c1" } }),
        MEDIA_BOOK,
      ),
    ).toBeUndefined();
    expect(
      mediaBookPublishErrorMessage(
        new ApiErrorObject({ status: 500, message: "x", detail: { code: "MEDIA_BOOK_IMAGE_UNAVAILABLE", cellId: "c1" } }),
        MEDIA_BOOK,
      ),
    ).toBeUndefined();
    expect(mediaBookPublishErrorMessage(new Error("network"), MEDIA_BOOK)).toBeUndefined();
  });
});
