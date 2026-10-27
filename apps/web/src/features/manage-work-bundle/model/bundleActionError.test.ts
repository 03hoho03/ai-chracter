import type { ApiError } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { toWorkBundleActionError } from "./bundleActionError";

function apiError(status: number, detail: ApiError["detail"]): ApiError {
  return { status, detail, message: "x" };
}

const LIMIT = apiError(409, { code: "WORK_BUNDLE_LIMIT" });

describe("toWorkBundleActionError", () => {
  it("재동의가 필요하면 null — 전역 재동의 모달에 맡기고 따로 알리지 않는다", () => {
    const reconsent = apiError(403, { code: "LEGAL_RECONSENT_REQUIRED", consents: [] });
    expect(toWorkBundleActionError(reconsent, "create")).toBeNull();
    expect(toWorkBundleActionError(reconsent, "addItem")).toBeNull();
  });

  it("같은 한도 409 라도 만들기는 묶음 수, 넣기는 항목 수를 말한다", () => {
    const create = toWorkBundleActionError(LIMIT, "create");
    const add = toWorkBundleActionError(LIMIT, "addItem");
    expect(create?.kind).toBe("bundleLimit");
    expect(create?.message).toContain("50개");
    expect(add?.kind).toBe("itemLimit");
    expect(add?.message).toContain("500개");
  });

  it("404 는 코드로 묶음이 없는 것과 작품을 넣을 수 없는 것을 가른다", () => {
    expect(toWorkBundleActionError(apiError(404, { code: "WORK_BUNDLE_NOT_FOUND" }), "addItem")?.kind).toBe("bundleGone");
    expect(toWorkBundleActionError(apiError(404, { code: "WORK_NOT_FOUND" }), "addItem")?.kind).toBe("workGone");
  });

  it("그 밖의 실패는 동작 이름을 붙여 다시 시도하라고 한다", () => {
    const unknown = toWorkBundleActionError(apiError(500, undefined), "rename");
    expect(unknown?.kind).toBe("unknown");
    expect(unknown?.message).toContain("이름");
  });
});
