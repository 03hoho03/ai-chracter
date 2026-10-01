import { beforeEach, describe, expect, it, vi } from "vitest";

import { commentApi } from "./commentApi";

const apiMocks = vi.hoisted(() => ({ get: vi.fn() }) as const);

vi.mock("@/shared/api/client", () => ({ apiClient: apiMocks }));

beforeEach(() => {
  apiMocks.get.mockReset();
  apiMocks.get.mockResolvedValue({ data: { items: [] } });
});

describe("comment reply page requests", () => {
  it("omits cursor parameters for the first page and forwards its abort signal", async () => {
    const signal = new AbortController().signal;

    await commentApi.replies("work", "root", undefined, signal);

    expect(apiMocks.get).toHaveBeenCalledWith("/contents/work/comments/root/replies", { params: undefined, signal });
  });

  it.each(["before", "after"] as const)("keeps the %s cursor when loading a located reply page", async (direction) => {
    const signal = new AbortController().signal;
    const page = { cursor: "cursor", direction };

    await commentApi.replies("work", "root", page, signal);

    expect(apiMocks.get).toHaveBeenCalledWith("/contents/work/comments/root/replies", { params: page, signal });
  });
});
