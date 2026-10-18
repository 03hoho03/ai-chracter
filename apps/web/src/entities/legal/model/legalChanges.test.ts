import { describe, expect, it } from "vitest";

import { type LegalChangeItem, selectChangesSinceOldestConsent, toChangeNoticeEntries } from "./legalChanges";

function item(version: string, effectiveAt: string, changeNotice: string | null = `${version} 안내`): LegalChangeItem {
  return { version, effectiveAt, changeNotice, reconsentScopes: [] };
}

// 시행 순서, 최신 판이 먼저. 같은 날 재게시한 `.10` 이 `.2` 보다 뒤에 시행됐다 — 문자열로는 `.10` < `.2` 다.
const ITEMS = [
  item("2026-10-18.10", "2026-10-18T09:00:00Z"),
  item("2026-10-18.2", "2026-10-18T05:00:00Z"),
  item("2026-10-17", "2026-10-17T04:25:18Z"),
  item("2026-10-12", "2026-10-12T00:00:00Z"),
  item("2026-09-06", "2026-09-06T00:00:00Z"),
];

const versionsOf = (items: LegalChangeItem[]) => items.map((i) => i.version);

describe("selectChangesSinceOldestConsent", () => {
  it("동의한 판보다 뒤에 시행된 판만, 최신 판부터 준다", () => {
    expect(versionsOf(selectChangesSinceOldestConsent(ITEMS, ["2026-10-12"]))).toEqual([
      "2026-10-18.10",
      "2026-10-18.2",
      "2026-10-17",
    ]);
  });

  // 문자열 비교로 고르면 `.2` 가 더 늦은 판이 되어 `.10` 을 기준으로 삼는다.
  it("같은 날 순번 판의 앞뒤를 문자열이 아니라 목록 위치로 정한다", () => {
    expect(versionsOf(selectChangesSinceOldestConsent(ITEMS, ["2026-10-18.2"]))).toEqual(["2026-10-18.10"]);
    expect(versionsOf(selectChangesSinceOldestConsent(ITEMS, ["2026-10-18.10", "2026-10-18.2"]))).toEqual([
      "2026-10-18.10",
    ]);
  });

  it("단위가 여럿이면 그중 가장 오래된 동의 판을 기준으로 한다", () => {
    expect(versionsOf(selectChangesSinceOldestConsent(ITEMS, ["2026-10-17", "2026-09-06"]))).toEqual([
      "2026-10-18.10",
      "2026-10-18.2",
      "2026-10-17",
      "2026-10-12",
    ]);
    // 순서를 바꿔 넣어도 같다.
    expect(selectChangesSinceOldestConsent(ITEMS, ["2026-09-06", "2026-10-17"])).toEqual(
      selectChangesSinceOldestConsent(ITEMS, ["2026-10-17", "2026-09-06"]),
    );
  });

  it("동의한 적 없거나 목록에 없는 판이 섞이면 전부 준다", () => {
    expect(selectChangesSinceOldestConsent(ITEMS, [null])).toHaveLength(ITEMS.length);
    expect(selectChangesSinceOldestConsent(ITEMS, ["2026-10-17", null])).toHaveLength(ITEMS.length);
    expect(selectChangesSinceOldestConsent(ITEMS, ["2025-01-01"])).toHaveLength(ITEMS.length);
    expect(selectChangesSinceOldestConsent(ITEMS, [])).toHaveLength(ITEMS.length);
  });

  it("최신 판에 이미 동의했으면 비어 있다", () => {
    expect(selectChangesSinceOldestConsent(ITEMS, ["2026-10-18.10"])).toEqual([]);
  });
});

describe("toChangeNoticeEntries", () => {
  it("시행일을 한국 날짜로 찍고 빈 안내는 null 로 접는다", () => {
    expect(
      toChangeNoticeEntries([
        item("2026-11-20", "2026-11-19T15:00:00Z", "- 바뀐 점"),
        item("2026-10-17", "2026-10-17T04:25:18Z", null),
        item("2026-10-12", "2026-10-12T00:00:00Z", "  \n "),
      ]),
    ).toEqual([
      { version: "2026-11-20", effectiveDate: "2026.11.20", notice: "- 바뀐 점" },
      { version: "2026-10-17", effectiveDate: "2026.10.17", notice: null },
      { version: "2026-10-12", effectiveDate: "2026.10.12", notice: null },
    ]);
  });
});
