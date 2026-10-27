import type { ApiError } from "@ai-character-chat/api-types";
import { describe, expect, it, vi } from "vitest";

import { addWorksInOrder, describeAddWorksResult } from "./addWorks";

/** 응답 인터셉터가 만드는 오류 꼴. 거절 값은 `Error` 여야 해서(린트) 같은 필드를 `Error` 에 얹는다. */
function apiError(status: number, code: string): Error & ApiError {
  return Object.assign(new Error("x"), { status, detail: { code } });
}

const works = ["a", "b", "c", "d"];

describe("addWorksInOrder", () => {
  it("모두 넣으면 넣은 수만 센다", async () => {
    const put = vi.fn(() => Promise.resolve());
    expect(await addWorksInOrder(works, put)).toEqual({ added: 4, gone: 0, stoppedBy: undefined, stopError: undefined });
    expect(put).toHaveBeenCalledTimes(4);
  });

  it("넣을 수 없는 작품은 건너뛰고 계속한다", async () => {
    const put = vi.fn((work: string) => (work === "b" ? Promise.reject(apiError(404, "WORK_NOT_FOUND")) : Promise.resolve()));
    const result = await addWorksInOrder(works, put);
    expect(result).toMatchObject({ added: 3, gone: 1, stoppedBy: undefined });
  });

  it("한도에 닿으면 그 자리에서 멈춘다 — 뒤 작품은 보내지 않는다", async () => {
    const put = vi.fn((work: string) => (work === "c" ? Promise.reject(apiError(409, "WORK_BUNDLE_LIMIT")) : Promise.resolve()));
    const result = await addWorksInOrder(works, put);
    expect(result).toMatchObject({ added: 2, gone: 0, stoppedBy: "itemLimit" });
    expect(put).toHaveBeenCalledTimes(3);
  });

  it("재동의가 필요하면 멈추고 그 오류를 함께 돌려준다", async () => {
    const error = apiError(403, "LEGAL_RECONSENT_REQUIRED");
    const result = await addWorksInOrder(works, () => Promise.reject(error));
    expect(result).toMatchObject({ added: 0, stoppedBy: "reconsent", stopError: error });
  });
});

describe("describeAddWorksResult", () => {
  it("모두 넣었으면 성공으로 수를 말한다", () => {
    expect(describeAddWorksResult({ added: 3, gone: 0, stoppedBy: undefined, stopError: undefined })).toEqual({
      tone: "success",
      message: "3개를 넣었어요.",
    });
  });

  it("건너뛴 작품이 있으면 넣은 수와 함께 말한다", () => {
    expect(describeAddWorksResult({ added: 2, gone: 1, stoppedBy: undefined, stopError: undefined })).toEqual({
      tone: "success",
      message: "2개를 넣었어요. 1개는 지워졌거나 넣을 수 없는 작품이라 건너뛰었어요.",
    });
  });

  it("한도에서 멈추면 넣은 수와 한도를 말한다(오류)", () => {
    const description = describeAddWorksResult({ added: 2, gone: 0, stoppedBy: "itemLimit", stopError: undefined });
    expect(description?.tone).toBe("error");
    expect(description?.message).toContain("2개를 넣고 멈췄어요");
    expect(description?.message).toContain("500개");
  });

  it("재동의로 멈추면 알리지 않는다", () => {
    expect(describeAddWorksResult({ added: 0, gone: 0, stoppedBy: "reconsent", stopError: undefined })).toBeNull();
  });
});
