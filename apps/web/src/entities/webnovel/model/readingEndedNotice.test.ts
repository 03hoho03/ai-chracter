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

  it("tells a buyer refunded after the publisher withdrew how much came back and points to the clover history", () => {
    const notice = toReadingEndedNotice("publisher_withdrawn", 45);
    expect(notice.body).toContain("45개는 돌려드렸어요");
    expect(notice.body).not.toContain("돌려드리지 않아요");
    expect(notice.actions).toEqual(["cloverHistory", "browse"]);
  });

  it("names the refunded amount when moderation closed the webnovel", () => {
    const notice = toReadingEndedNotice("restricted", 1200);
    expect(notice.body).toContain("1,200개는 돌려드렸어요");
    expect(notice.actions).toEqual(["cloverHistory", "browse"]);
  });

  it("tells a buyer refunded because of the source that a reopened webnovel has to be bought again", () => {
    const notice = toReadingEndedNotice("source_unavailable", 30);
    expect(notice.body).toContain("30개를 돌려드렸어요");
    expect(notice.body).toContain("다시 소장할 수 있어요");
    expect(notice.actions).toEqual(["cloverHistory", "browse"]);
  });

  it("does not promise that owned chapters reopen when a withdrawn webnovel was refunded", () => {
    const notice = toReadingEndedNotice("withdrawn", 30);
    expect(notice.body).toContain("30개");
    expect(notice.body).not.toContain("다시 열려요");
    expect(notice.actions).toEqual(["cloverHistory", "browse"]);
  });

  it.each([
    ["publisher_withdrawn", "탈퇴하면 소설이 바로 지워져요. 이 경우 클로버는 돌려드리지 않아요."],
    ["withdrawn", "게시자가 공개를 거뒀어요. 다시 공개되면 소장한 화도 다시 열려요."],
    ["restricted", "운영 정책에 따라 이용이 제한됐어요."],
    ["source_unavailable", "원작이 다시 공개되면 이 소설도 다시 볼 수 있어요."],
    ["service_off", "다시 열면 소장한 화도 그대로 볼 수 있어요."],
  ] as const)("keeps the unrefunded wording for %s when nothing came back", (reason, body) => {
    const notice = toReadingEndedNotice(reason, 0);
    expect(notice.body).toBe(body);
    expect(notice.actions).not.toContain("cloverHistory");
  });

  it("falls back to a reason-free notice for a reason this screen does not know", () => {
    expect(toReadingEndedNotice(undefined, 0).title).toBe("지금은 볼 수 없는 소설이에요");
  });
});
