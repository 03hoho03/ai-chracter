import { describe, expect, it } from "vitest";

import { toEditionNotice } from "./editionNotice";

const BOUGHT = { edition: 1, publishedAt: "2026-10-12T03:00:00Z", changeSummary: null };
const LATEST = { edition: 3, publishedAt: "2026-10-18T03:00:00Z", changeSummary: "결말 문단을 고쳤어요" };

describe("toEditionNotice", () => {
  it.each([null, undefined])("구매 당시 판이 %s 면 안내가 없다", (purchasedEdition) => {
    expect(toEditionNotice({ edition: 3, purchasedEdition, latestEdition: LATEST })).toBeUndefined();
  });

  it("지금 판을 읽는 중이면 구매 당시 판을 권하고 두 판의 날짜·요약을 싣는다", () => {
    expect(toEditionNotice({ edition: 3, purchasedEdition: BOUGHT, latestEdition: LATEST })).toEqual({
      kind: "newerAvailable",
      purchased: { edition: 1, dateLabel: "2026.10.12", summary: undefined },
      latest: { edition: 3, dateLabel: "2026.10.18", summary: "결말 문단을 고쳤어요" },
    });
  });

  it("구매 당시 판을 읽는 중이면 최신 판을 권한다", () => {
    expect(toEditionNotice({ edition: 1, purchasedEdition: BOUGHT, latestEdition: LATEST })?.kind).toBe(
      "readingPurchased",
    );
  });

  it("구매 당시 판에 요약이 있으면 그것도 싣는다", () => {
    const bought = { ...BOUGHT, edition: 2, changeSummary: "오타를 고쳤어요" };
    expect(toEditionNotice({ edition: 3, purchasedEdition: bought, latestEdition: LATEST })?.purchased.summary).toBe(
      "오타를 고쳤어요",
    );
  });

  it.each([null, "", "   "])("요약이 %o 면 요약 자리를 비운다", (changeSummary) => {
    expect(
      toEditionNotice({ edition: 3, purchasedEdition: BOUGHT, latestEdition: { ...LATEST, changeSummary } })?.latest
        ?.summary,
    ).toBeUndefined();
  });

  it.each([null, undefined])("최신 판 칸이 %s 인 옛 서버면 최신 판 정보 없이 한 줄만 낸다", (latestEdition) => {
    const notice = toEditionNotice({ edition: 3, purchasedEdition: BOUGHT, latestEdition });
    expect(notice?.kind).toBe("newerAvailable");
    expect(notice?.latest).toBeUndefined();
  });

  it("공개 날짜는 한국 날짜로 찍는다", () => {
    expect(
      toEditionNotice({
        edition: 2,
        purchasedEdition: { ...BOUGHT, publishedAt: "2026-10-11T15:30:00Z" },
        latestEdition: { ...LATEST, publishedAt: "2026-10-17T15:30:00Z" },
      }),
    ).toMatchObject({ purchased: { dateLabel: "2026.10.12" }, latest: { dateLabel: "2026.10.18" } });
  });
});
