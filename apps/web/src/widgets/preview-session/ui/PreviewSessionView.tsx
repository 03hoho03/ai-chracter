import { useEffect, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ChevronLeft, RotateCw, Send, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import type { PreviewShortcut, PreviewStartPayload } from "../../../entities/preview-session";
import { usePreviewSessionQuery, useStartPreviewMutation } from "../../../entities/preview-session";
import { usePreviewSendMessage } from "../../../features/preview-chat";
import { ShortcutAutocomplete } from "../../../features/shortcut-autocomplete";
import { EndingDivider, MessageBubble, StatGaugePanel, TypingIndicator } from "../../../entities/chat-room";
import { shouldShowSuggestedReplies } from "../../../shared/lib/suggested-replies/shouldShowSuggestedReplies";

function PreviewSkeleton() {
  return (
    <div className="flex h-[calc(100dvh-3.5rem)] items-center justify-center px-6">
      <p className="text-sm text-muted-foreground">미리보기 세션을 여는 중이에요...</p>
    </div>
  );
}

// techspec-builder-common.md §3 — 빌더 어디서든 열리는 테스트 대화 화면. 실제 채팅의 순수
// 프레젠테이션 컴포넌트(메시지 리스트/스탯 게이지)는 entities/chat-room, 단축어 자동완성은
// features/shortcut-autocomplete에서 그대로 재사용하되, 데이터 레이어(entities/preview-session)는
// 완전히 분리되어 있다 — 스탯/키워드북/단축어/엔딩 판정은 실제 채팅과 동일한 서버 로직(US-089)이
// 그대로 처리하고 이 화면은 그 결과만 반영한다. getPayload는 호출 시점의 최신 폼 값
// (formToServer(getValues()))을 돌려주는 함수로, "미리보기 초기화"도 이 함수를 다시 호출해
// 최신 폼 값 기준 새 세션을 연다.
export function PreviewSessionView({
  getPayload,
  onClose,
}: {
  getPayload: () => PreviewStartPayload;
  onClose?: () => void;
}) {
  const startMutation = useStartPreviewMutation();
  const [previewSessionId, setPreviewSessionId] = useState<string>();
  const stateQuery = usePreviewSessionQuery(previewSessionId);
  const state = stateQuery.data;

  const { send, isSending, error, policyWarning, streamingText } = usePreviewSendMessage(previewSessionId);
  const [text, setText] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const startedRef = useRef(false);

  // mutate()의 콜백 인자(onSuccess) 대신 mutateAsync()를 쓰고, 로딩 상태도 startMutation.isPending이
  // 아니라 로컬 isStarting으로 직접 관리한다 — 이 함수는 마운트 시 useEffect에서 곧바로 호출되는데,
  // React StrictMode의 마운트→언마운트→재마운트 시뮬레이션과 겹치면 그 첫 호출의 MutationObserver
  // 구독이 순간적으로 해제됐다가 재구독되면서 원래 뮤테이션 알림(콜백·isPending·data 전부)에서 영구히
  // 떨어져나간다(개발 모드에서만 재현, 실측 — widgets/content-detail/lib/usePlayContent.ts의 start()가
  // 이미 mutateAsync를 쓰는 것과 같은 이유). mutateAsync()가 반환하는 프로미스 자체는 그 알림 경로와
  // 무관하게 정상적으로 settle되므로, 결과 처리를 전부 이 함수 안에서 직접 끝낸다.
  async function startPreview() {
    setIsStarting(true);
    try {
      const nextState = await startMutation.mutateAsync(getPayload());
      setPreviewSessionId(nextState.previewSessionId);
    } catch {
      toast.error("미리보기 세션을 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsStarting(false);
    }
  }

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void startPreview();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [state?.messages.length, streamingText]);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;
    void send(trimmed);
    setText("");
  }

  function handleShortcutSelect(shortcut: PreviewShortcut) {
    if (isSending) return;
    void send(shortcut.prompt, shortcut.id);
    setText("");
  }

  if (!state) {
    return <PreviewSkeleton />;
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          {onClose && (
            <Button variant="ghost" size="icon-sm" aria-label="미리보기 닫기" onClick={onClose}>
              <ChevronLeft aria-hidden className="size-4" />
            </Button>
          )}
          <span className="text-sm font-semibold text-foreground">미리보기</span>
        </div>
        <Button variant="outline" size="sm" onClick={startPreview} disabled={isStarting}>
          <RotateCw aria-hidden className="size-3.5" />
          미리보기 초기화
        </Button>
      </header>

      {state.statDefs.length > 0 && <StatGaugePanel stats={state.statDefs} values={state.stats} />}

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="flex flex-col gap-3">
          {state.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}

          {state.endingStatus.reached && state.endingStatus.epilogue && (
            <>
              <EndingDivider />
              <MessageBubble
                message={{ id: "ending-epilogue", role: "assistant", content: state.endingStatus.epilogue, createdAt: "" }}
              />
            </>
          )}

          {isSending &&
            (streamingText ? (
              <MessageBubble message={{ id: "streaming", role: "assistant", content: streamingText, createdAt: "" }} />
            ) : (
              <TypingIndicator />
            ))}

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5">
              <span className="text-xs text-destructive">응답 생성에 실패했습니다.</span>
            </div>
          )}

          {policyWarning && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3.5 py-2.5">
              <TriangleAlert aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">{policyWarning}</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-background p-3">
        {/* 실제 채팅방(ChatRoomView)과 동일한 규칙 — 첫 턴 전송을 시작한 순간부터 감춘다.
            turnCount는 스트림 종료(done)에야 오르므로 isSending 게이트가 없으면
            첫 응답이 스트리밍되는 내내 죽은 칩 줄이 남는다. */}
        {!isSending && shouldShowSuggestedReplies(state.suggestedReplies, state.turnCount) && (
          <div className="mb-2 flex gap-2 overflow-x-auto pb-0.5">
            {state.suggestedReplies.map((reply) => (
              <Button
                key={reply}
                type="button"
                variant="secondary"
                size="sm"
                disabled={isSending}
                onClick={() => void send(reply)}
                className="shrink-0 rounded-full"
              >
                {reply}
              </Button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <div className="relative flex-1">
            <Textarea
              ref={inputRef}
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSend();
                }
              }}
              placeholder="메시지를 입력하세요"
              disabled={isSending}
              rows={1}
              className="max-h-40 resize-none"
            />
            {state.shortcuts.length > 0 && text.startsWith("/") && (
              <ShortcutAutocomplete
                shortcuts={state.shortcuts}
                query={text.slice(1)}
                onSelect={handleShortcutSelect}
              />
            )}
          </div>
          <Button size="icon" aria-label="전송" disabled={isSending || !text.trim()} onClick={handleSend}>
            <Send aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
