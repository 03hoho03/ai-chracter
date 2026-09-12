import { useEffect, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { RotateCw, Send, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import type { PreviewShortcut, PreviewStartPayload } from "@/entities/preview-session";
import {
  EndingDivider,
  MessageBubble,
  StatGaugePanel,
  TypingIndicator,
  shouldShowSuggestedReplies,
} from "@/entities/chat-room";
import { buildPreviewStartState, usePreviewSessionQuery, useStartPreviewMutation } from "@/entities/preview-session";
import { usePreviewSendMessage } from "@/features/preview-chat";
import { ShortcutAutocomplete } from "@/features/shortcut-autocomplete";

import { PreviewCloseHeader } from "./PreviewCloseHeader";

// techspec-builder-common.md §3 — 빌더 어디서든 열리는 테스트 대화 화면. 실제 채팅의 순수
// 프레젠테이션 컴포넌트(메시지 리스트/스탯 게이지)는 entities/chat-room, 단축어 자동완성은
// features/shortcut-autocomplete에서 그대로 재사용하되, 데이터 레이어(entities/preview-session)는
// 완전히 분리되어 있다 — 스탯/키워드북/단축어/엔딩 판정은 실제 채팅과 동일한 서버 로직(US-089)이
// 그대로 처리하고 이 화면은 그 결과만 반영한다. getPayload는 호출 시점의 최신 폼 값
// (formToServer(getValues()))을 돌려주는 함수로, "미리보기 초기화"도 이 함수를 다시 호출해
// 최신 폼 값 기준 새 세션을 연다.
//
// D-7(builder-techspec.md §6-2) — 서버 세션은 마운트가 아니라 첫 전송 때 생긴다. 그 전까지는
// buildPreviewStartState로 계산한 로컬 플레이스홀더만 그린다(BE의 _build_preview_start_state를
// 그대로 재현하므로 화면은 세션이 있을 때와 같다). 입력창·단축어·추천답변 세 전송 경로가 전부
// ensurePreviewSession()을 거쳐 세션을 보장한 뒤에야 usePreviewSendMessage의 send()를 부른다.
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
  // A-8(builder-progress.md) — usePreviewSessionQuery는 enabled:false라 캐시는 오직
  // useStartPreviewMutation의 성공 콜백으로만 채워진다. 지연 시작 이후 첫 전송 전에는 그 캐시가
  // 비어 있으므로, 세션 id 없이 계산한 로컬 상태로 대신한다 — 안 그러면 첫 전송 전까지 영구
  // 스켈레톤이 된다.
  const state = stateQuery.data ?? buildPreviewStartState(undefined, getPayload());

  const { send, status, policyWarning, streamingText } = usePreviewSendMessage();
  const isSending = status.kind === "sending";
  const [text, setText] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // mutate()의 콜백 인자(onSuccess) 대신 mutateAsync()를 쓰고, 로딩 상태도 startMutation.isPending이
  // 아니라 로컬 isStarting으로 직접 관리한다 — apps/web/CLAUDE.md "마운트 시 뮤테이션은
  // mutateAsync+await+로컬 로딩 state"와 같은 이유(widgets/content-detail/lib/usePlayContent.ts의
  // start()도 동일)로, 이 함수는 이제 마운트가 아니라 첫 전송 시점에 호출되지만 StrictMode
  // 마운트→언마운트→재마운트 취약성은 뮤테이션 훅 자체의 성질이라 여전히 적용된다.
  async function startPreview(): Promise<string | undefined> {
    setIsStarting(true);
    try {
      const nextState = await startMutation.mutateAsync(getPayload());
      setPreviewSessionId(nextState.previewSessionId);
      return nextState.previewSessionId;
    } catch {
      toast.error("미리보기 세션을 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
      return undefined;
    } finally {
      setIsStarting(false);
    }
  }

  // 세 전송 경로(입력창·단축어·추천답변) 공통 "세션 보장" 함수 — 이미 세션이 있으면 그대로 쓰고,
  // 없으면 이 시점의 getPayload()로 새로 만든다.
  async function ensurePreviewSession(): Promise<string | undefined> {
    if (previewSessionId) return previewSessionId;
    return startPreview();
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [state.messages.length, streamingText]);

  // ensurePreviewSession()이 돌려준 id를 send()에 직접 태운다 — usePreviewSendMessage가 훅 레벨
  // 파라미터 대신 호출마다 id를 받는 이유(features/preview-chat/model/usePreviewSendMessage.ts 참고)가
  // 바로 이 지점: 세션을 막 만든 직후엔 컴포넌트가 아직 그 id로 재렌더되지 않아 previewSessionId
  // state를 참조하면 stale한 undefined를 잡는다.
  async function sendWithSession(content: string, shortcutId?: string) {
    const id = await ensurePreviewSession();
    if (!id) return;
    void send(id, content, shortcutId);
  }

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || isSending || isStarting) return;
    setText("");
    void sendWithSession(trimmed);
  }

  function handleShortcutSelect(shortcut: PreviewShortcut) {
    if (isSending || isStarting) return;
    setText("");
    void sendWithSession(shortcut.prompt, shortcut.id);
  }

  function handleSuggestedReplyClick(reply: string) {
    if (isSending || isStarting) return;
    void sendWithSession(reply);
  }

  return (
    <div className="flex h-below-header flex-col">
      <PreviewCloseHeader
        onClose={onClose}
        action={
          <Button variant="outline" size="sm" onClick={() => void startPreview()} disabled={isStarting}>
            <RotateCw aria-hidden className="size-3.5" />
            미리보기 초기화
          </Button>
        }
      />

      <div className="mx-auto flex w-full min-h-0 max-w-5xl flex-1 flex-col">
        {state.statDefs.length > 0 && <StatGaugePanel stats={state.statDefs} values={state.stats} />}

        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
          <div className="flex flex-col gap-3">
            {state.messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {state.endingStatus.reached && !!state.endingStatus.epilogue && (
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

            {status.kind === "error" && (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5">
                <span className="text-xs text-destructive-text">응답 생성에 실패했습니다.</span>
              </div>
            )}

            {!!policyWarning && (
              <div className="flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3.5 py-2.5">
                <TriangleAlert aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">{policyWarning}</span>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-border bg-background px-4 sm:px-6 py-3">
          {/* 실제 채팅방(ChatRoomView)과 동일한 규칙 — 첫 턴 전송을 시작한 순간부터 감춘다.
              사용자 메시지가 전송 즉시 캐시에 추가되므로, turnCount가 오르기를 기다리는
              동안(스트리밍 구간) 죽은 칩 줄이 남는 것도 이 항이 함께 막는다. */}
          {shouldShowSuggestedReplies(
            state.suggestedReplies,
            state.turnCount,
            state.messages.some((message) => message.role === "user"),
          ) && (
            <div className="mb-2 flex gap-2 overflow-x-auto pb-0.5">
              {state.suggestedReplies.map((reply) => (
                <Button
                  key={reply}
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={isSending || isStarting}
                  onClick={() => handleSuggestedReplyClick(reply)}
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
            <Button
              size="icon"
              aria-label="전송"
              disabled={isSending || isStarting || !text.trim()}
              onClick={handleSend}
            >
              <Send aria-hidden className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
