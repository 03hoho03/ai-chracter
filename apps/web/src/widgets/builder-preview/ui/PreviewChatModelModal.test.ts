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
    expect(modalSource).toContain("needsConfirm={(modelId) => previewModelNeedsConfirm(modelId, hasSession)}");
  });
});
