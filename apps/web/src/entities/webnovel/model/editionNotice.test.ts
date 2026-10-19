import { describe, expect, it } from "vitest";

import { toEditionNotice } from "./editionNotice";

describe("toEditionNotice", () => {
  it.each([null, undefined])("산 때의 판이 %s 면 안내가 없다", (purchasedEdition) => {
    expect(toEditionNotice({ edition: 3, purchasedEdition })).toBeUndefined();
  });

  it("지금 판을 읽는 중이면 산 때의 판을 권한다", () => {
    expect(toEditionNotice({ edition: 3, purchasedEdition: { edition: 1, publishedAt: "2026-10-12T03:00:00Z" } })).toEqual({
      kind: "newerAvailable",
      purchasedEdition: 1,
      purchasedDateLabel: "2026.10.12",
    });
  });

  it("산 때의 판을 읽는 중이면 최신 판을 권한다", () => {
    expect(toEditionNotice({ edition: 1, purchasedEdition: { edition: 1, publishedAt: "2026-10-12T03:00:00Z" } })?.kind).toBe(
      "readingPurchased",
    );
  });

  it("공개 날짜는 한국 날짜로 찍는다", () => {
    expect(
      toEditionNotice({ edition: 2, purchasedEdition: { edition: 1, publishedAt: "2026-10-11T15:30:00Z" } })?.purchasedDateLabel,
    ).toBe("2026.10.12");
  });
});
