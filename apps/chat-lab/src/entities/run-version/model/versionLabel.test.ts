import { describe, expect, it } from "vitest";

import type { HostedVersion } from "@/shared/api/service/serviceClient";

import { versionNumberText, versionSizeText } from "./versionLabel";

function version(overrides: Partial<HostedVersion> = {}): HostedVersion {
  return {
    sha256: "a".repeat(64),
    versionNumber: 3,
    uploadedAt: "2026-11-05T05:02:00Z",
    uploadedBy: "test-client.access",
    raw: false,
    contractVersion: 1,
    sourceCommit: { commit: "abc1234".padEnd(40, "0"), dirty: false },
    provenance: {
      passed: true,
      baseLocal: true,
      roomFound: true,
      ownerInExampleDomain: true,
      outsideUsers: 0,
      exemptedUsers: 0,
      authorInExampleDomain: true,
    },
    compressedSize: 1258291,
    uncompressedSize: 6710886,
    ...overrides,
  };
}

describe("versionNumberText", () => {
  it("최신 판 번호와 살아 있는 판 수를 함께 쓴다 — 번호만 보면 판이 몇 개 남았는지 모른다", () => {
    expect(versionNumberText(version({ versionNumber: 3 }), 2)).toBe("3 · 살아 있는 판 2개");
    expect(versionNumberText(version({ versionNumber: 1 }), 1)).toBe("1 · 살아 있는 판 1개");
  });
});

describe("versionSizeText", () => {
  it("압축 크기와 푼 크기를 MiB 소수 한 자리로 쓴다", () => {
    expect(versionSizeText(version())).toBe("압축 1.2MiB · 푼 6.4MiB");
  });
});
