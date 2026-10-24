import { describe, expect, it } from "vitest";

import { isSummaryRegenerateOffered } from "./regenerateOffer";

describe("isSummaryRegenerateOffered", () => {
  it("offers regeneration only while its route is open and summaries are used in replies", () => {
    expect(isSummaryRegenerateOffered({ itemsVisible: true, summaryFolding: true })).toBe(true);
  });

  it("does not sell a summary that replies would not use", () => {
    expect(isSummaryRegenerateOffered({ itemsVisible: true, summaryFolding: false })).toBe(false);
  });

  it("stays hidden while the route is closed", () => {
    expect(isSummaryRegenerateOffered({ itemsVisible: false, summaryFolding: true })).toBe(false);
  });
});
