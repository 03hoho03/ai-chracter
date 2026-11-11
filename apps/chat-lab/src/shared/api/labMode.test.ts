import { afterEach, describe, expect, it, vi } from "vitest";

import { pickLabMode } from "./labMode";
import { STATIC_BUNDLE_ELEMENT_ID } from "./staticBundleElement";

/** 정적 묶음 태그에 실릴 글 — 판정은 겉모양만 보므로 꼭 필요한 칸만 채운다. */
const STATIC_BUNDLE_TEXT = JSON.stringify({
  contractVersion: 1,
  raw: false,
  detail: { run: { runId: "cnVucy9hL2NoYXQuanNvbmw" }, turns: [] },
  metrics: { turns: [] },
  turns: [],
});

describe("pickLabMode", () => {
  it("정적 묶음이 실린 문서는 호스팅 빌드여도 정적이다 — 파일로 연 화면은 어느 서버에도 닿지 않는다", () => {
    expect(pickLabMode({ isHostedBuild: true, staticKind: "ready" })).toBe("static");
    expect(pickLabMode({ isHostedBuild: false, staticKind: "ready" })).toBe("static");
  });

  it("읽지 못한 정적 묶음도 정적이다 — 서버로 넘어가지 않는다", () => {
    expect(pickLabMode({ isHostedBuild: true, staticKind: "broken" })).toBe("static");
    expect(pickLabMode({ isHostedBuild: false, staticKind: "broken" })).toBe("static");
  });

  it("실린 묶음이 없고 호스팅 빌드면 호스팅이다", () => {
    expect(pickLabMode({ isHostedBuild: true, staticKind: "absent" })).toBe("hosted");
  });

  it("실린 묶음이 없고 호스팅 빌드가 아니면 로컬이다", () => {
    expect(pickLabMode({ isHostedBuild: false, staticKind: "absent" })).toBe("local");
  });
});

describe("labMode", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  /**
   * 빌드 상수와 문서를 흉내 내고 모듈을 새로 읽는다. 정적 묶음 상태는 처음 읽은 값을 모듈 변수에 두므로, 시험마다 모듈 기록을
   * 비워야 앞 시험의 문서가 남지 않는다.
   */
  async function loadLabMode(mode: string | undefined, staticBundleText: string | null) {
    vi.stubEnv("VITE_CHAT_LAB_MODE", mode);
    vi.stubGlobal("document", {
      getElementById: (id: string) =>
        id === STATIC_BUNDLE_ELEMENT_ID && staticBundleText !== null ? { textContent: staticBundleText } : null,
    });
    vi.resetModules();
    const { labMode } = await import("./labMode");
    return labMode;
  }

  it("빌드 상수가 hosted 이고 실린 묶음이 없으면 호스팅이다", async () => {
    const labMode = await loadLabMode("hosted", null);

    expect(labMode()).toBe("hosted");
  });

  it("빌드 상수가 없으면 로컬이다", async () => {
    const labMode = await loadLabMode(undefined, null);

    expect(labMode()).toBe("local");
  });

  it("빌드 상수가 hosted 와 한 글자라도 다르면 호스팅으로 넘어가지 않는다 — 오타는 빌드가 막고, 실행 중에도 정확히 같을 때만 호스팅이다", async () => {
    for (const typo of ["hostd", "Hosted", " hosted", "hosted ", "true", ""]) {
      const labMode = await loadLabMode(typo, null);

      expect(labMode(), JSON.stringify(typo)).toBe("local");
    }
  });

  it("호스팅 빌드라도 정적 묶음이 실린 문서는 정적이다 — 호스팅 빌드 결과로 내보낸 정적 HTML 도 정적으로 돈다", async () => {
    const labMode = await loadLabMode("hosted", STATIC_BUNDLE_TEXT);

    expect(labMode()).toBe("static");
  });

  it("호스팅 빌드에 읽지 못한 정적 묶음이 실려도 정적이다", async () => {
    const labMode = await loadLabMode("hosted", "{");

    expect(labMode()).toBe("static");
  });

  it("부를 때마다 빌드 상수를 다시 읽는다 — 시험이 모듈을 다시 읽지 않고도 갈래를 바꿀 수 있다", async () => {
    const labMode = await loadLabMode("hosted", null);
    expect(labMode()).toBe("hosted");

    vi.stubEnv("VITE_CHAT_LAB_MODE", undefined);

    expect(labMode()).toBe("local");
  });
});
