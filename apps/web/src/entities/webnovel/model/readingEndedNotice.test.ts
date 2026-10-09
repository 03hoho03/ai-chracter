import { describe, expect, it } from "vitest";

import { toReadingEndedNotice } from "./readingEndedNotice";
import { WEBNOVEL_ENDED_REASONS } from "./webnovelError";

describe("toReadingEndedNotice", () => {
  it("tells a refunded buyer how much came back and points to the clover history", () => {
    const notice = toReadingEndedNotice("deleted", 60);
    expect(notice.body).toContain("60개");
    expect(notice.actions).toEqual(["cloverHistory", "browse"]);
  });

  it("does not claim a refund when nothing came back from a deletion", () => {
    const notice = toReadingEndedNotice("deleted", 0);
    expect(notice.body).not.toContain("돌려드렸어요");
    expect(notice.actions).not.toContain("cloverHistory");
  });

  it("sends readers home rather than to the list while the webnovel service is off", () => {
    expect(toReadingEndedNotice("service_off", 0).actions).toEqual(["home"]);
  });

  it("gives every known reason its own title", () => {
    const titles = WEBNOVEL_ENDED_REASONS.map((reason) => toReadingEndedNotice(reason, 30).title);
    expect(new Set(titles).size).toBe(WEBNOVEL_ENDED_REASONS.length);
  });

  it("falls back to a reason-free notice for a reason this screen does not know", () => {
    expect(toReadingEndedNotice(undefined, 0).title).toBe("지금은 볼 수 없는 소설이에요");
  });
});
