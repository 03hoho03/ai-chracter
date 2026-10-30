import { describe, expect, it } from "vitest";

// 화면 소스는 문자열로 읽는다 — 이 위젯은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import roomPickerSource from "@/features/select-chat-model/ui/ChatModelPicker.tsx?raw";

import modalSource from "./PreviewChatModelModal.tsx?raw";

// 미리보기와 대화방의 모델 목록·확인 블록은 한 벌이어야 한다. 한쪽이 사본을 그리면 다음 손질에서 문장·모양·접근성 연결이 갈린다.
describe("preview chat model modal", () => {
  it("대화방 래퍼와 미리보기 모달이 같은 목록 화면을 그린다", () => {
    expect(roomPickerSource).toContain("<ChatModelOptions");
    expect(modalSource).toContain("<ChatModelOptions");
  });

  it("미리보기 모달은 목록 행·확인 문장을 직접 그리지 않는다", () => {
    expect(modalSource).not.toContain("ToggleGroup");
    expect(modalSource).not.toContain("formatPremiumModelConfirm");
    expect(modalSource).not.toContain("무료 대화 없이");
  });

  it("세션이 있을 때의 확인 판정을 미리보기 판정 함수로 넘긴다", () => {
    expect(modalSource).toContain("needsConfirm={(modelId) => previewModelNeedsConfirm(models, modelId, hasSession)}");
  });
});

// 세션 중에 바꾸면 처음부터 다시 시작한다는 문장은 모달에 한 번만 보여야 한다. 설명과 확인 블록 양쪽에 두면 눈으로도
// 낭독기로도 두 번이고, 상위 모델 확인 문장의 "바꾸면 …" 뒤에 같은 머리말이 이어 붙는다.
describe("preview chat model modal restart note", () => {
  const description = modalSource.slice(
    modalSource.indexOf("<DialogDescription"),
    modalSource.indexOf("</DialogDescription>"),
  );

  it("다이얼로그 설명에는 다시 시작 문장이 없다", () => {
    expect(description).not.toBe("");
    expect(description).not.toContain("RESTART_NOTE");
    expect(description).not.toContain("처음부터 다시");
  });

  it("다시 시작 문장은 세션이 있을 때 확인 블록 하나에만 간다", () => {
    expect(modalSource).toContain("confirmNote={hasSession ? RESTART_NOTE : undefined}");
    expect(modalSource.match(/\{?RESTART_NOTE\b/g)).toHaveLength(2);
  });

  it("다시 시작 문장은 상위 모델 확인 문장과 머리말이 겹치지 않는다", () => {
    expect(modalSource).not.toMatch(/const RESTART_NOTE = "바꾸면/);
  });
});
