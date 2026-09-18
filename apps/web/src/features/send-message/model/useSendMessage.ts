import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { characterImageArchiveKeys } from "@/entities/character-image-archive";
import {
  applyStreamEvent,
  buildEditPayload,
  buildRegeneratePayload,
  buildSendPayload,
  chatRoomKeys,
  dropLastMessage,
  getChatRateLimit,
  restoreMessage,
  truncateAndEdit,
} from "@/entities/chat-room";
import { chatStreamEventSchema } from "@/entities/chat-room";
import type { ChatMessage, ChatRateLimit, ChatRoomState, ChatStreamRequest } from "@/entities/chat-room";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { sessionKeys } from "@/entities/session";
import { openChatStream } from "@/shared/api/sse/openChatStream";

type PendingRequest = { payload: ChatStreamRequest; kind: "newTurn" | "regenerate" };

// TS-04 — isSending(boolean) + error(SendMessageError | null)의 조합은 "전송 중이면서 동시에
// 에러"라는 불가능 상태를 타입으로 막지 못했다. 판별 유니언으로 상태를 하나로 묶는다.
// limit-goal-prompt.md RL-15 — 429는 안내 문구와 다음 행동이 다른 오류라(기다리면 풀린다) 배너가
// 분기할 수 있게 `rateLimit`을 함께 싣는다. 429가 아닌 실패는 값이 없고 기존 배너 그대로다.
type SendMessageStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "error"; retryPayload: PendingRequest; rateLimit?: ChatRateLimit };

/** techspec-chat-common.md §1 — 낙관적 업데이트가 핵심: 사용자 메시지는 스트림 성공 여부와
 * 무관하게 먼저 캐시에 반영해 실패해도 화면에서 사라지지 않는다(FR-88).
 * characterId는 캐릭터 챗일 때만(스토리 챗은 undefined) 전달 — 상황별 이미지가 트리거된
 * 메시지가 도착하면 이미지 보관함(US-074) 쿼리를 무효화한다(techspec-chat-character.md §1.2). */
export function useSendMessage(roomId: string, characterId?: string) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SendMessageStatus>({ kind: "idle" });
  const [policyWarning, setPolicyWarning] = useState<string>();
  const [streamingText, setStreamingText] = useState("");

  async function openStream(pending: PendingRequest) {
    setStatus({ kind: "sending" });
    setPolicyWarning(undefined);
    setStreamingText("");
    // finally에서 status를 읽으면 위 setStatus가 아직 반영되지 않은 클로저 값을 보므로, 이번 스트림에서
    // 에러가 났는지는 로컬 변수로 따로 추적한다.
    let hasErrored = false;
    // RU-1·RU-2·RU-11(2) — 재생성 클릭 즉시 옛 답변을 지운다(retry()도 pending.kind를 그대로
    // 승계해 같은 분기를 탄다). 진행 중인 재조회를 먼저 끊지 않으면 뒤늦게 도착한 응답이 그 제거를
    // 되돌린다.
    // 🔴 cancelQueries를 재생성일 때만 부르는 이유: 기본값이 `revert: true`라 취소되는 fetch가
    // *시작된 시점의* 캐시로 되돌린다(query-core `query.js`의 #revertState). send()/editMessage()는
    // 낙관적 변경을 openStream 호출 *전에* 하므로, 무조건 부르면 방금 추가한 사용자 메시지나 편집
    // 절단이 조용히 사라진다. 재생성은 제거가 이 줄 *뒤*라 그 창이 없다.
    let dropped: ChatMessage | undefined;
    if (pending.kind === "regenerate") {
      await queryClient.cancelQueries({ queryKey: chatRoomKeys.detail(roomId) });
      dropped = dropLastMessage(queryClient, roomId);
    }
    // RU-3 — "done을 봤다"가 아니라 "done을 캐시에 반영했다"다(onDone은 setQueryData 업데이터
    // 안에서 불리므로 캐시가 없으면 호출되지 않는다). 실패 분기를 열거하지 않고 이 값 하나로
    // 복원 여부를 판단한다.
    let hasCommitted = false;

    try {
      for await (const event of openChatStream(pending.payload, chatStreamEventSchema)) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          hasErrored = true;
          // 스트림 안에서 온 오류는 상한과 무관하다(게이트는 스트림이 열리기 전에 429로 막는다).
          setStatus({ kind: "error", retryPayload: pending });
        }
        applyStreamEvent(queryClient, roomId, event, {
          kind: pending.kind,
          onDone: (message) => {
            hasCommitted = true;
            if (message.imageId && characterId) {
              void queryClient.invalidateQueries({ queryKey: characterImageArchiveKeys.list(characterId) });
            }
          },
        });
      }
    } catch (error) {
      hasErrored = true;
      // RL-17 — SSE는 뮤테이션이 아니라 `app/AppProviders.tsx`의 MutationCache.onError가 못 본다.
      // 재동의 403을 여기서 잡지 않으면 채팅 4경로에서만 모달이 뜨지 않는다(세션을 다시 조회하면
      // ReconsentModal이 `GET /me`의 플래그로 뜬다 — CG-12와 같은 처리다).
      if (isLegalReconsentRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      }
      setStatus({ kind: "error", retryPayload: pending, rateLimit: getChatRateLimit(error) });
    } finally {
      setStreamingText("");
      // RU-4 — 동기 롤백 + invalidate 둘 다. 롤백만으로는 서버가 실제로 커밋한 경우 화면이 서버와
      // 어긋난 채 남고, invalidate만으로는 왕복 동안 메시지가 빠진 화면이 유지된다.
      if (dropped && !hasCommitted) {
        restoreMessage(queryClient, roomId, dropped);
        void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
      }
      if (!hasErrored) setStatus({ kind: "idle" });
    }
  }

  function send(text: string, shortcutId?: string): void {
    const optimisticMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    queryClient.setQueryData<ChatRoomState>(
      chatRoomKeys.detail(roomId),
      (prev) => prev && { ...prev, messages: [...prev.messages, optimisticMessage] },
    );

    void openStream({ payload: buildSendPayload({ roomId, text, shortcutId }), kind: "newTurn" });
  }

  // techspec-chat-common.md §2.1 — 마지막 AI 응답만 새 텍스트로 교체(같은 턴), 새 사용자
  // 메시지를 추가하지 않는다.
  function regenerate(): void {
    if (status.kind === "sending") return;
    void openStream({ payload: buildRegeneratePayload({ roomId }), kind: "regenerate" });
  }

  // truncateAndEdit로 그 메시지 이후를 먼저 잘라낸 뒤, 일반 전송과 동일한 스트리밍 흐름을
  // 재실행한다(편집 대상 이후 새 응답을 append) — send()와 달리 낙관적 사용자 메시지를 새로
  // 추가하지 않는다(이미 캐시에 있는 메시지를 truncateAndEdit이 갱신한다).
  function editMessage(messageId: string, text: string): void {
    if (status.kind === "sending") return;
    truncateAndEdit(queryClient, roomId, messageId, text);
    void openStream({ payload: buildEditPayload({ roomId, messageId, text }), kind: "newTurn" });
  }

  function retry(): void {
    if (status.kind !== "error") return;
    // 동일 payload로 스트림만 재오픈 — 사용자 메시지를 중복 추가하지 않음(send()를 다시 호출하지 않음).
    void openStream(status.retryPayload);
  }

  return { send, retry, regenerate, editMessage, status, policyWarning, streamingText };
}
