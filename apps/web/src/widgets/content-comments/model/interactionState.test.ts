import { describe, expect, it } from "vitest";

import { resolveThreadExpanded, resolveSavedTarget } from "./interactionState";

describe("comment interaction override ownership", () => {
  it("keeps a manual collapse for its anchor, but opens a newly located target", () => {
    const collapsed = { anchor: "A", isExpanded: false };
    expect(resolveThreadExpanded(collapsed, "A", true)).toBe(false);
    expect(resolveThreadExpanded(collapsed, "B", true)).toBe(true);
    expect(resolveThreadExpanded(collapsed, undefined, false)).toBe(false);
    expect(resolveThreadExpanded({ isExpanded: true }, undefined, false)).toBe(true);
    expect(resolveThreadExpanded(undefined, undefined, false)).toBe(false);
    expect(resolveThreadExpanded(undefined, "A", true)).toBe(true);
  });
  it("retains a saved target only within the external target that owned the save", () => {
    const saved = { sourceTargetId: "notification-A", commentId: "new-reply" };
    expect(resolveSavedTarget(saved, "notification-A")).toBe("new-reply");
    expect(resolveSavedTarget(saved, "notification-B")).toBe("notification-B");
    expect(resolveSavedTarget({ commentId: "new-root" }, undefined)).toBe("new-root");
    expect(resolveSavedTarget(undefined, "notification-B")).toBe("notification-B");
  });
});
