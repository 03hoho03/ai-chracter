import { describe, expect, it } from "vitest";

import { findStaticTurn, parseStaticBundle } from "./staticBundle";

const RUN_ID = "cnVucy9hL2NoYXQuanNvbmw";

/** 측정 서버의 통째 응답 꼴(런 상세·지표·턴 상세 전부). 파서가 겉모양만 보므로 각 칸은 꼭 필요한 만큼만 채운다. */
function bundleJson(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    raw: false,
    detail: { run: { runId: RUN_ID }, turns: [] },
    metrics: { turns: [] },
    turns: [
      { turn: 1, attempts: [] },
      { turn: 2, attempts: [] },
    ],
    ...overrides,
  });
}

function readyBundle(text: string) {
  const state = parseStaticBundle(text);
  if (state.kind !== "ready") throw new Error(`주입 데이터를 읽지 못했다: ${state.kind}`);
  return state.bundle;
}

describe("parseStaticBundle", () => {
  it("주입 태그가 없으면 없음 — 측정 서버를 읽는 화면이다", () => {
    expect(parseStaticBundle(null)).toEqual({ kind: "absent" });
    expect(parseStaticBundle(undefined)).toEqual({ kind: "absent" });
  });

  it("태그 글이 통째 응답이면 그 묶음을 그대로 낸다", () => {
    const text = bundleJson();

    expect(parseStaticBundle(text)).toEqual({ kind: "ready", bundle: JSON.parse(text) });
  });

  it("깨진 JSON 은 없음이 아니라 깨짐이다 — 측정 서버를 읽는 화면으로 넘어가 서버를 띄우라는 틀린 안내를 보이지 않는다", () => {
    expect(parseStaticBundle('{"raw": false, "detail": ').kind).toBe("broken");
  });

  it("태그는 있는데 글이 비었으면 깨짐이다", () => {
    expect(parseStaticBundle("").kind).toBe("broken");
    expect(parseStaticBundle("  \n").kind).toBe("broken");
  });

  it("JSON 이지만 통째 응답 꼴이 아니면 깨짐이다 — 측정 서버의 거부 본문을 잘못 실은 파일도 여기에 든다", () => {
    expect(parseStaticBundle(JSON.stringify({ detail: "그런 묶음이 없다", reason: "notFound" })).kind).toBe("broken");
    expect(parseStaticBundle("null").kind).toBe("broken");
    expect(parseStaticBundle("[]").kind).toBe("broken");
    expect(parseStaticBundle(bundleJson({ turns: undefined })).kind).toBe("broken");
    expect(parseStaticBundle(bundleJson({ raw: "false" })).kind).toBe("broken");
    expect(parseStaticBundle(bundleJson({ detail: { turns: [] } })).kind).toBe("broken");
  });

  it("`detail.run` 이 객체여도 런 id 가 없거나 문자열이 아니면 깨짐이다 — 첫 화면이 갈 런을 정할 수 없다", () => {
    expect(parseStaticBundle(bundleJson({ detail: { run: {}, turns: [] } })).kind).toBe("broken");
    expect(parseStaticBundle(bundleJson({ detail: { run: { runId: 42 }, turns: [] } })).kind).toBe("broken");
    expect(parseStaticBundle(bundleJson({ detail: { run: { runId: null }, turns: [] } })).kind).toBe("broken");
  });

  it("깨짐에는 사람이 읽을 까닭이 붙는다", () => {
    const state = parseStaticBundle("{");

    expect(state.kind === "broken" && state.reason.length > 0).toBe(true);
  });
});

describe("findStaticTurn", () => {
  it("턴 번호로 그 턴 상세를 찾는다(배열 순번이 아니라 번호로)", () => {
    const bundle = readyBundle(bundleJson({ turns: [{ turn: 3 }, { turn: 5 }] }));

    expect(findStaticTurn(bundle, 5)).toEqual({ turn: 5 });
    expect(findStaticTurn(bundle, 3)).toEqual({ turn: 3 });
  });

  it("파일에 없는 턴이면 undefined — 부르는 쪽이 없는 턴으로 낸다", () => {
    const bundle = readyBundle(bundleJson());

    expect(findStaticTurn(bundle, 99)).toBeUndefined();
    expect(findStaticTurn(bundle, 0)).toBeUndefined();
  });
});
