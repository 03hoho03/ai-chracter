import { describe, expect, it } from "vitest";

import {
  canAccessExistingRoom,
  canDiscoverPublicly,
  canViewDetailPage,
  resolveAccessStatus,
  toContentAccessStatus,
  toContentStatusTags,
} from "./content";

describe("resolveAccessStatus", () => {
  it("returns deleted when moderationStatus is deleted, regardless of visibility", () => {
    expect(resolveAccessStatus("public", "deleted")).toEqual({ kind: "deleted" });
    expect(resolveAccessStatus("private", "deleted")).toEqual({ kind: "deleted" });
  });

  it("returns restricted when moderationStatus is restricted, regardless of visibility", () => {
    expect(resolveAccessStatus("public", "restricted")).toEqual({ kind: "restricted" });
    expect(resolveAccessStatus("private", "restricted")).toEqual({ kind: "restricted" });
  });

  it("returns accessible with the visibility when moderationStatus is normal", () => {
    expect(resolveAccessStatus("public", "normal")).toEqual({ kind: "accessible", visibility: "public" });
    expect(resolveAccessStatus("link", "normal")).toEqual({ kind: "accessible", visibility: "link" });
    expect(resolveAccessStatus("private", "normal")).toEqual({ kind: "accessible", visibility: "private" });
  });
});

describe("canDiscoverPublicly", () => {
  it("is true only for accessible + public", () => {
    expect(canDiscoverPublicly({ kind: "accessible", visibility: "public" })).toBe(true);
  });

  it("is false for accessible + link or private", () => {
    expect(canDiscoverPublicly({ kind: "accessible", visibility: "link" })).toBe(false);
    expect(canDiscoverPublicly({ kind: "accessible", visibility: "private" })).toBe(false);
  });

  it("is false for restricted or deleted", () => {
    expect(canDiscoverPublicly({ kind: "restricted" })).toBe(false);
    expect(canDiscoverPublicly({ kind: "deleted" })).toBe(false);
  });
});

describe("canAccessExistingRoom", () => {
  it("is false only for restricted or deleted moderationStatus", () => {
    expect(canAccessExistingRoom("restricted")).toBe(false);
    expect(canAccessExistingRoom("deleted")).toBe(false);
  });

  it("is true for normal moderationStatus regardless of visibility", () => {
    expect(canAccessExistingRoom("normal")).toBe(true);
  });
});

describe("canViewDetailPage", () => {
  it("blocks restricted and deleted for owner and non-owner alike", () => {
    expect(canViewDetailPage({ kind: "restricted" }, true)).toBe(false);
    expect(canViewDetailPage({ kind: "restricted" }, false)).toBe(false);
    expect(canViewDetailPage({ kind: "deleted" }, true)).toBe(false);
    expect(canViewDetailPage({ kind: "deleted" }, false)).toBe(false);
  });

  it("allows private only for the owner", () => {
    expect(canViewDetailPage({ kind: "accessible", visibility: "private" }, true)).toBe(true);
    expect(canViewDetailPage({ kind: "accessible", visibility: "private" }, false)).toBe(false);
  });

  it("allows public and link for everyone", () => {
    expect(canViewDetailPage({ kind: "accessible", visibility: "public" }, false)).toBe(true);
    expect(canViewDetailPage({ kind: "accessible", visibility: "link" }, false)).toBe(true);
  });
});

describe("toContentAccessStatus", () => {
  it("keeps visibility only when kind is accessible", () => {
    expect(toContentAccessStatus({ kind: "accessible", visibility: "link" })).toEqual({
      kind: "accessible",
      visibility: "link",
    });
  });

  it("drops visibility for restricted and deleted", () => {
    expect(toContentAccessStatus({ kind: "restricted", visibility: null })).toEqual({ kind: "restricted" });
    expect(toContentAccessStatus({ kind: "deleted" })).toEqual({ kind: "deleted" });
  });
});

describe("toContentStatusTags", () => {
  it("공개범위 배지 하나만 낸다 — moderationStatus가 normal이면", () => {
    expect(toContentStatusTags({ visibility: "public", moderationStatus: "normal" })).toEqual(["public"]);
    expect(toContentStatusTags({ visibility: "link", moderationStatus: "normal" })).toEqual(["link"]);
    expect(toContentStatusTags({ visibility: "private", moderationStatus: "normal" })).toEqual(["private"]);
  });

  it("이용제한이면 공개범위 배지와 restricted를 함께 낸다", () => {
    expect(toContentStatusTags({ visibility: "public", moderationStatus: "restricted" })).toEqual([
      "public",
      "restricted",
    ]);
    expect(toContentStatusTags({ visibility: "private", moderationStatus: "restricted" })).toEqual([
      "private",
      "restricted",
    ]);
  });
});
