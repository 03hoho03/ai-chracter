import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

import { copyCodeToClipboard } from "./copyCodeToClipboard";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("copyCodeToClipboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("writes the code and shows a success toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await copyCodeToClipboard("상태 *값*");

    expect(writeText).toHaveBeenCalledWith("상태 *값*");
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("shows a failure toast when the clipboard rejects", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });

    await copyCodeToClipboard("x");

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  // 보안 컨텍스트가 아니면 clipboard 자체가 없다 — 던지지 말고 실패로 안내한다.
  it("shows a failure toast when the clipboard API is missing", async () => {
    vi.stubGlobal("navigator", {});

    await copyCodeToClipboard("x");

    expect(toast.error).toHaveBeenCalledTimes(1);
  });
});
