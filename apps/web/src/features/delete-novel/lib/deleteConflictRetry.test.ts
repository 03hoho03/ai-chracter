import { describe, expect, it, vi } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { withDeleteConflictRetry } from "./deleteConflictRetry";

function apiError(status: number, detail: Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, detail, message: "error" });
}

describe("withDeleteConflictRetry", () => {
  it("새 소장자 경합 409 면 한 번 다시 보내 그 결과를 돌려준다", async () => {
    const send = vi.fn().mockRejectedValueOnce(apiError(409, { code: "NOVEL_DELETE_CONFLICT" })).mockResolvedValueOnce("ok");
    await expect(withDeleteConflictRetry(send)).resolves.toBe("ok");
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("두 번째도 경합이면 더 보내지 않고 던진다", async () => {
    const conflict = apiError(409, { code: "NOVEL_DELETE_CONFLICT" });
    const send = vi.fn().mockRejectedValue(conflict);
    await expect(withDeleteConflictRetry(send)).rejects.toBe(conflict);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("다른 409 와 다른 실패는 다시 보내지 않는다", async () => {
    for (const error of [apiError(409, { code: "NOVEL_BATCH_NOT_LAST" }), apiError(500, undefined), new Error("network")]) {
      const send = vi.fn().mockRejectedValue(error);
      await expect(withDeleteConflictRetry(send)).rejects.toBe(error);
      expect(send).toHaveBeenCalledTimes(1);
    }
  });
});
