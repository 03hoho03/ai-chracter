import { describe, expect, it } from "vitest";

import type { LabMode } from "@/shared/api/labMode";

import { rawAbsentText } from "./rawAbsentText";
import type { RawView } from "./rawSource";

type AbsentView = Exclude<RawView, { kind: "text" }>;

/** 세 모드 전부 — `Record` 라 모드가 늘면 여기서 컴파일이 막힌다. */
const MODE_COVERAGE = { local: true, static: true, hosted: true } as const satisfies Record<LabMode, true>;
const MODES = Object.keys(MODE_COVERAGE) as LabMode[];

const STATIC_EXCLUDED_PROMPT =
  "원문 제외 — 이 파일은 프롬프트·지시문 원문을 빼고 내보냈다. 원문까지 보려면 원문 포함(--raw)으로 다시 내보낸다.";
const STATIC_EXCLUDED_INSTRUCTION =
  "원문 제외 — 이 파일은 원문 없이 내보내, 이 호출이 지시문을 따로 보냈는지도 이 파일로는 알 수 없다. 원문까지 보려면 원문 포함(--raw)으로 다시 내보낸다.";

describe("rawAbsentText", () => {
  it("정적 파일의 원문 제외 문장은 다시 내보내라고 말한다", () => {
    expect(rawAbsentText({ kind: "excluded", field: "prompt" }, "static")).toBe(STATIC_EXCLUDED_PROMPT);
    expect(rawAbsentText({ kind: "excluded", field: "systemInstruction" }, "static")).toBe(STATIC_EXCLUDED_INSTRUCTION);
  });

  it("호스팅 화면의 원문 제외 문장은 올린 사람이 다시 올리라고 말한다", () => {
    expect(rawAbsentText({ kind: "excluded", field: "prompt" }, "hosted")).toBe(
      "원문 제외 — 이 판은 프롬프트·지시문 원문을 빼고 올렸다. 원문까지 보려면 올린 사람이 원문 포함(--raw)으로 다시 올린다.",
    );
    expect(rawAbsentText({ kind: "excluded", field: "systemInstruction" }, "hosted")).toBe(
      "원문 제외 — 이 판은 원문 없이 올려, 이 호출이 지시문을 따로 보냈는지도 이 판으로는 알 수 없다. 원문까지 보려면 올린 사람이 원문 포함(--raw)으로 다시 올린다.",
    );
  });

  it("로컬 화면의 원문 제외 문장은 옮기기 전 문장 그대로다", () => {
    expect(rawAbsentText({ kind: "excluded", field: "prompt" }, "local")).toBe(STATIC_EXCLUDED_PROMPT);
    expect(rawAbsentText({ kind: "excluded", field: "systemInstruction" }, "local")).toBe(STATIC_EXCLUDED_INSTRUCTION);
  });

  it("그 밖의 갈래 문장은 모드와 상관없고 옮기기 전 문장 그대로다", () => {
    const cases: Array<[AbsentView, string]> = [
      [{ kind: "noDumpFile", text: "측정 서버가 준 원문 자리 문장" }, "측정 서버가 준 원문 자리 문장"],
      [
        { kind: "notSelectedAttempt", earlierCount: 2 },
        "덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다. 이 턴의 앞선 생성 덤프 2개는 어느 시도의 것인지 가르지 않아 출처에서 따로 연다.",
      ],
      [{ kind: "notSelectedAttempt", earlierCount: 0 }, "덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다."],
      [{ kind: "noDumpForAttempt" }, "덤프 없음 — 이 출처에 붙은 덤프 줄이 없다."],
      [{ kind: "emptyPrompt" }, "이 덤프 줄의 프롬프트 칸이 비어 있다 — 칸은 있지만 글이 아닌 값이 적혀 있다."],
      [{ kind: "noField" }, "이 덤프 줄에는 지시문 칸이 없다 — 지시문을 따로 보내지 않은 호출이다."],
    ];

    for (const [view, sentence] of cases) {
      for (const mode of MODES) {
        expect(rawAbsentText(view, mode), `${view.kind} · ${mode}`).toBe(sentence);
      }
    }
  });
});
