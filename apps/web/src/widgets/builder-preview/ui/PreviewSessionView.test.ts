import { describe, expect, it } from "vitest";

// 화면 소스는 문자열로 읽는다 — 이 위젯은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import viewSource from "./PreviewSessionView.tsx?raw";

describe("PreviewSessionView", () => {
  // 미리보기 응답의 id 는 UUID 지만 DB 에 저장되지 않아, 신고를 붙이면 서버가 404 를 낸다.
  // id 형식으로는 저장된 메시지와 구분되지 않으므로 신고 콜백을 아예 넘기지 않는 것으로 막는다.
  it("never wires the chat response report into the builder preview", () => {
    expect(viewSource).toContain("<MessageBubble");
    expect(viewSource).not.toContain("onReport");
  });
});

// 세션이 끝나 거절된 미리보기(첫 전송의 세션 생성 거절 포함)는 실패 배너·"잠시 후 다시 시도" 토스트가 아니라 안내를 띄운다.
describe("PreviewSessionView session-ended notice", () => {
  it("routes both the send rejection and the session-start rejection to the notice before the failure banner", () => {
    expect(viewSource).toContain("startSessionEnded ?? (status.kind === \"error\" ? status.sessionEnded : undefined)");
    expect(viewSource).toContain("if (sessionEnded) setStartSessionEnded(sessionEnded);");
    const notice = viewSource.indexOf("<SessionEndedNotice reason={sessionEnded} />");
    expect(notice).toBeGreaterThan(-1);
    expect(notice).toBeLessThan(viewSource.indexOf("응답 생성에 실패했습니다."));
  });
});

// 확인 모달에 넘기는 한 턴 가격은 지금 답을 쓰는 모델의 가격이어야 한다. 기본 모델 가격을 고정해 넘기면 상위 모델을 고른 화면에서 숫자가 틀린다.
describe("PreviewSessionView turn cost", () => {
  it("confirms clover spend with the displayed model's price, not the default model's", () => {
    expect(viewSource).not.toContain("defaultChatTurnCost");
    expect(viewSource).toContain("const turnCost = previewTurnCost(models, displayModelId);");
    expect(viewSource).toContain("confirmCloverSpend(error, turnCost, \"chat\")");
  });

  it("starts the session with the displayed model's query", () => {
    expect(viewSource).toContain("query: previewStartQuery(displayModelId),");
  });
});

// 상위 모델 허용이 그 사이 꺼져 시작이 403 으로 거절되면, 다시 보내면 기본 모델로 열리므로 이용자가 쓴 글이 사라지면 안 된다.
describe("PreviewSessionView model-not-allowed start rejection", () => {
  const branchStart = viewSource.indexOf("if (isChatModelNotAllowedError(error)) {");
  const branch = viewSource.slice(branchStart, viewSource.indexOf("return undefined;", branchStart));

  it("handles the rejection before the session-ended branch", () => {
    expect(branchStart).toBeGreaterThan(-1);
    expect(branchStart).toBeLessThan(viewSource.indexOf("const sessionEnded = getSessionEndReason(error);"));
  });

  it("falls back to the default model, refreshes access and restores the typed text", () => {
    expect(branch).toContain("toast.error(CHAT_MODEL_NOT_ALLOWED_MESSAGE);");
    expect(branch).toContain("setChosenModelId(DEFAULT_CHAT_MODEL);");
    expect(branch).toContain("invalidateChatModelAccess(queryClient);");
    expect(branch).toContain("onModelNotAllowed?.();");
  });

  it("the input send path passes a callback that puts the sent text back", () => {
    expect(viewSource).toContain(
      "void sendWithSession(trimmed, undefined, () => setText((current) => (current === \"\" ? text : current)));",
    );
  });
});

// 상위 모델 미리보기의 클로버 부족 배너는 자정 약속이 없는 문구여야 한다.
describe("PreviewSessionView rate limit surface", () => {
  it("picks the premium preview surface from the displayed model", () => {
    expect(viewSource).toContain('surface={isPremiumChatModel(displayModelId) ? "premiumPreview" : "preview"}');
    expect(viewSource).not.toContain('surface="preview"');
  });
});

// 모델을 바꾸면 세션 id 가 비고 대화가 처음으로 돌아간다. 앞 세션 턴의 배너(레이트리밋·본인인증·그만둠·실패)가 남으면 막히지 않은
// 새 모델 위에 옛 배너가 남고, 레이트리밋 문구가 새 모델로 다시 골라져 거짓이 된다.
describe("PreviewSessionView send error after the session is cleared", () => {
  it("draws the send-result banners only while a session id is set", () => {
    expect(viewSource).toContain(
      'const sendError = status.kind === "error" && previewSessionId !== undefined ? status : undefined;',
    );
    expect(viewSource).toContain("} else if (sendError) {");
    expect(viewSource).toContain("rateLimit={sendError.rateLimit}");
    expect(viewSource).toContain("} else if (sendError.identityRequired) {");
    expect(viewSource).toContain("} else if (sendError.declined) {");
    expect(viewSource).not.toMatch(/status\.(rateLimit|identityRequired|declined)/);
  });

  it("changing the model clears the session id", () => {
    const chooseStart = viewSource.indexOf("async function handleChooseModel() {");
    const choose = viewSource.slice(chooseStart, viewSource.indexOf("\n  }\n", chooseStart));
    expect(choose).toContain("setPreviewSessionId(undefined);");
  });
});
