import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  addStatDelta,
  applyStreamEvent,
  buildRoomTurnAnnouncement,
  buildEditPayload,
  buildRegeneratePayload,
  buildSendPayload,
  chatRoomKeys,
  countRepliesAfter,
  dropLastMessage,
  getChatRateLimit,
  isContentRestrictedError,
  selectRoomScene,
} from "@/entities/chat-room";
import { chatStreamEventSchema } from "@/entities/chat-room";
import type {
  ChatMessage,
  ChatRateLimit,
  ChatRoomState,
  ChatStreamRequest,
  StatDeltas,
  StatRewind,
  StatTurnFeedback,
} from "@/entities/chat-room";
import {
  allowanceAfterCloverConfirm,
  canAskCloverConfirm,
  FIRST_CLOVER_CONFIRM_ALLOWANCE,
  readCloverPricing,
} from "@/entities/clover";
import type { CloverSpendConfirmOutcome } from "@/entities/clover";
import { isIdentityVerificationRequiredError } from "@/entities/identity";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { getSessionEndReason, resetSessionIfLost, sessionKeys, type SessionEndReason } from "@/entities/session";
import { isApiError } from "@/shared/api/client";
import { openChatStream } from "@/shared/api/sse/openChatStream";

import { addOptimisticUserMessage } from "./addOptimisticUserMessage";
import { ensureUserMessageForSend } from "./ensureUserMessageForSend";
import { expandUserTextForRoom } from "./expandUserTextForRoom";
import { imageArchiveKeyToInvalidate, type ImageArchiveTarget } from "./imageArchiveKeyToInvalidate";
import { settleTurnInProgress } from "./settleTurnInProgress";
import { settleTurnStreamEnd } from "./settleTurnStreamEnd";
import { truncateForEditAttempt } from "./truncateForEditAttempt";

// `messagesBeforeEdit`는 수정의 첫 시도 직전 목록이다. 재시도 요청에 실어 다녀야 앞 턴 거절 때 원래 목록으로 되돌린다.
type PendingRequest = {
  payload: ChatStreamRequest;
  kind: "newTurn" | "regenerate";
  messagesBeforeEdit?: ChatMessage[];
};

// isSending(boolean) + error(SendMessageError | null)의 조합은 "전송 중이면서 동시에
// 에러"라는 불가능 상태를 타입으로 막지 못했다. 판별 유니언으로 상태를 하나로 묶는다.
// 429는 안내 문구와 다음 행동이 다른 오류라(기다리면 풀린다) 배너가
// 분기할 수 있게 `rateLimit`을 함께 싣는다. 429가 아닌 실패는 값이 없고 기존 배너 그대로다.
// `declined`는 **사용자가 확인 모달에서 그만둔 것**이라
// 실패가 아니다. 같은 `error` 자리를 쓰는 이유는 낙관적 사용자 메시지가 이미 목록에 있어
// 아무것도 안 보여 주면 멈춘 것처럼 읽히기 때문이고(재시도 버튼도 그대로 유용하다), 문구만
// 배너가 갈라 쓴다 — 실패하지 않은 일에 "실패했습니다"를 쓰면 거짓이다.
// `restricted`는 작품이 이용제한·삭제돼 서버가 거부한 것이다. 기다려도 다시 보내도 안 풀리므로 화면은 재시도 대신
// 입력창 자리에 안내를 띄운다(방을 열 때 이미 제한이었다면 응답의 `contentRestricted`가 같은 일을 한다).
// `busy`는 같은 방의 앞 턴이 아직 끝나지 않아 서버가 시작 전에 거절한 것이다. 기다리면 풀리므로 실패 배너가 아니라
// 중립 배너와 다시 보내기를 띄운다.
// `identityRequired`는 본인인증 전이라 무료 대화가 없고 가진 클로버도 모자라 서버가 막은 것이다. 다시 보내도 안 풀리고
// 실패도 아니라 재시도 대신 본인인증 안내를 띄운다.
// `sessionEnded`는 세션이 끝나(로그인이 풀렸거나 정지) 서버가 거절한 것이다. 응답 생성이 실패한 것이 아니고 이 탭에서는
// 다시 보내도 같은 거절이라, 재시도 대신 까닭에 맞는 안내(다시 로그인 / 문의처)를 띄운다.
type SendMessageStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | {
      kind: "error";
      retryPayload: PendingRequest;
      rateLimit?: ChatRateLimit;
      declined?: boolean;
      restricted?: boolean;
      busy?: boolean;
      identityRequired?: boolean;
      sessionEnded?: SessionEndReason;
    };

/** 낙관적 업데이트가 핵심: 사용자 메시지는 스트림 성공 여부와
 * 무관하게 먼저 캐시에 반영해 실패해도 화면에서 사라지지 않는다.
 * imageArchive는 이 방의 작품(캐릭터·스토리) — 턴이 해금을 바꿨을 수 있으면 그 작품의 이미지 보관함 쿼리를
 * 무효화한다(무엇이 해금을 바꾸는지는 `imageArchiveKeyToInvalidate`). */
export function useSendMessage(
  roomId: string,
  imageArchive?: ImageArchiveTarget,
  /** 오류를 받아 **"재시도해도 되는가"** 를 돌려준다.
   *
   * 🔴 위젯이 주입하는 이유는 FSD다 — 모달은 `features/confirm-clover-spend`에 있고 feature가
   * 다른 feature를 import하는 선례가 이 저장소에 **0건**이다(`.call()` 호출부는 전부
   * `widgets`/`pages`이거나 같은 슬라이스 안이다). 단가도 표면마다 달라 위젯이 **미리 묶어**
   * 넘긴다 — 그래서 이 훅은 클로버 단가를 알 필요가 없다.
   *
   * 안 넘기면 확인 429가 평소의 오류 배너로 떨어질 뿐 동작은 깨지지 않는다 — 다만 그 화면에서는
   * 클로버를 영영 못 쓴다. */
  confirmCloverSpend?: (error: unknown) => Promise<CloverSpendConfirmOutcome>,
  /** 재생성이 새 답을 방 캐시에 반영하고 스트림이 끝났을 때 그 답을 받는다(되돌리기 안내를 띄우는 자리). 재생성의 재시도·클로버
   * 동의 뒤 재전송이 성공해도 한 번 불린다. */
  onRegenerated?: (message: ChatMessage) => void,
  /** 수정이 새 답을 방 캐시에 반영하고 스트림이 끝났을 때, 서버가 지운 턴의 스탯을 어떻게 했는지 받는다(안내 토스트를 띄우는
   * 자리). 지운 턴이 없던 수정이거나 그 칸을 보내지 않는 서버면 undefined 다. */
  onEdited?: (statRewind: StatRewind | undefined) => void,
) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SendMessageStatus>({ kind: "idle" });
  const [policyWarning, setPolicyWarning] = useState<string>();
  const [streamingText, setStreamingText] = useState("");
  // 확정된 마지막 턴이 상태 줄에 알릴 것(증감 칩·익명 신호·스크린리더 안내). 다음 턴이 시작되면 거둔다 — 익명 신호는 다음
  // 메시지를 보낼 때까지 남는다. 방 이동·초기화·되돌리기는 이 훅이 모르므로, 화면은 `selectVisibleTurnFeedback` 으로
  // 그 턴의 방·응답이 아직 지금 것인지 가려 보인다. `turn` 은 이 훅 안에서만 쓰는 일련번호다.
  const [turnFeedback, setTurnFeedback] = useState<StatTurnFeedback>();
  const turnFeedbackSeqRef = useRef(0);

  /** `allowance`는 **무한 루프 차단기**다. 동의 뒤 재시도는
   * 그 확인을 뺀 값으로 들어가므로, 재시도가 또 `CLOVER_CONFIRM_REQUIRED`를 받아도 모달을 다시 띄우지 않고
   * 평범한 오류로 끝난다. 가격 바뀜 확인 뒤의 재시도는 하루 한 번 확인을 아직 물을 수 있다 — 서버가 가격 버전을 그 확인보다
   * 먼저 대조해서다(`entities/clover` 의 `CloverConfirmAllowance`).
   *
   * ⚠️ 이 차단기가 막는 것은 **"서버가 동의를 인정하지 않는 경우"** 하나뿐이다. 흔히 드는 두 사유는
   * 여기서 성립하지 않는다:
   * - *동의 POST 실패* — `useConfirmCloverSpend`가 그때 `false`를 돌려주므로 **재시도 자체가 없다**.
   * - *자정을 막 넘김* — 채팅 일일 키에는 KST 날짜가 섞여 있어(`core/rate_limit_gate.py`의
   *   `_DAY_SCOPE` 키 조립) 자정에 카운트가 0으로 리셋되고, 그러면 클로버 분기에 **도달조차
   *   하지 않아** 재전송이 무료로 통과한다. 이 사유가 참인 것은 시간당 충전이라 자정과 무관한
   *   **이미지 쪽**이다.
   *
   * 그래서 재시도는 **커밋된 동의** 뒤에만 일어나고 서버는 통과시켜야 정상이다. 차단기는 그
   * "정상"을 FE가 증명할 수 없다는 사실에 대한 보험이다 — 게이트 조건이 나중에 바뀌는 등으로
   * 둘의 판단이 갈리면, 없을 때 그 불일치가 **무한 왕복**이 된다. 사용자 조작 한 번당 모달을
   * 한 번으로 묶는 것이 이 인자의 전부다. */
  async function openStream(request: PendingRequest, allowance = FIRST_CLOVER_CONFIRM_ALLOWANCE) {
    setStatus({ kind: "sending" });
    setPolicyWarning(undefined);
    setStreamingText("");
    setTurnFeedback(undefined);
    // finally에서 status를 읽으면 위 setStatus가 아직 반영되지 않은 클로저 값을 보므로, 이번 스트림에서
    // 에러가 났는지는 로컬 변수로 따로 추적한다.
    let hasErrored = false;
    // 재생성 클릭 즉시 옛 답변을 지운다(retry()도 pending.kind를 그대로
    // 승계해 같은 분기를 탄다). 진행 중인 재조회를 먼저 끊지 않으면 뒤늦게 도착한 응답이 그 제거를
    // 되돌린다.
    // 🔴 cancelQueries를 재생성일 때만 부르는 이유: 기본값이 `revert: true`라 취소되는 fetch가
    // *시작된 시점의* 캐시로 되돌린다(query-core `query.js`의 #revertState). send()/editMessage()는
    // 낙관적 변경을 이 줄보다 *앞에서* 하므로, 무조건 부르면 방금 추가한 사용자 메시지나 편집
    // 절단이 조용히 사라진다. 재생성은 제거가 이 줄 *뒤*라 그 창이 없다.
    let dropped: ChatMessage | undefined;
    // 턴을 보내기 직전 상태 줄이 보이던 장면 — 확정된 장면과 견줘 바뀐 칸만 안내한다. 수정의 절단·재생성의 제거보다 먼저 읽어야
    // 사용자가 보고 있던 장면이다.
    const roomBeforeTurn = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId));
    const sceneBeforeTurn = roomBeforeTurn && selectRoomScene(roomBeforeTurn);
    // 편집 절단을 여기서 하는 이유: retry()가 같은 payload로 다시 들어올 때도 같은 절단을 다시 한다. 되돌릴 목록은
    // 첫 시도 것을 이어 받아 이후의 retryPayload에 실린다.
    const pending: PendingRequest = {
      ...request,
      messagesBeforeEdit: truncateForEditAttempt(queryClient, roomId, request.payload, request.messagesBeforeEdit),
    };
    if (pending.kind === "regenerate") {
      await queryClient.cancelQueries({ queryKey: chatRoomKeys.detail(roomId) });
      dropped = dropLastMessage(queryClient, roomId);
    }
    // "done을 봤다"가 아니라 "done을 캐시에 반영했다"다(onDone은 setQueryData 업데이터
    // 안에서 불리므로 캐시가 없으면 호출되지 않는다). 실패 분기를 열거하지 않고 이 값 하나로
    // 복원 여부를 판단한다.
    let hasCommitted = false;
    let committedMessage: ChatMessage | undefined;
    // 이번 턴의 증감은 캐시의 직전 값과 `statChange` 새 값의 차다. 재생성은 서버가 그 턴의 스탯을 반영 전 값으로 되돌린 뒤
    // 다시 판정하므로 캐시의 직전 값(옛 응답의 결과)과의 차는 이번 턴의 변화가 아니다 — 칩을 세우지 않는다. 익명 신호는
    // 서버가 `statChange` 와 따로, 턴 시작 값(반영 전 값)과 이번 판정 결과가 다른 신호 켠 숨긴 스탯으로 정해 보낸다. 재생성도
    // 같은 기준이라 그대로 쓴다.
    let deltas: StatDeltas = {};
    let hiddenSignal = false;
    // 수정은 서버가 편집 지점 뒤에서 지운 응답 수만큼 턴 수를 줄인다. 첫 시도 직전 목록으로 센다 — 재시도 때 캐시는 이미
    // 잘려 있어 세면 0 이다. 실패한 시도 사이에 방을 다시 받았으면 이 셈이 어긋날 수 있는데, done 뒤 방을 다시 받아 맞춘다.
    const removedReplyCount =
      pending.payload.kind === "edit"
        ? countRepliesAfter(pending.messagesBeforeEdit ?? [], pending.payload.messageId)
        : 0;
    let statRewind: StatRewind | undefined;
    // 서버가 HTTP 오류 응답으로 시작 전에 거절했는가 — `openChatStream` 은 그때만 `ApiError` 를 던지고, 스트림이 열린 뒤의 끊김은
    // 네트워크 오류로 온다.
    let wasRejected = false;

    try {
      // 가격 버전은 내용(`pending.payload`)에 굳히지 않고 여는 순간 캐시에서 읽는다 — 가격 바뀜 확인 뒤 재전송과 다시
      // 보내기가 같은 내용에 다시 받은 가격표의 버전을 싣는다.
      const priceVersion = readCloverPricing(queryClient)?.priceVersion;
      for await (const event of openChatStream(pending.payload, chatStreamEventSchema, { priceVersion })) {
        if (event.type === "token") {
          setStreamingText((prev) => prev + event.delta);
        } else if (event.type === "policyWarning") {
          setPolicyWarning(event.message);
        } else if (event.type === "error") {
          hasErrored = true;
          // 스트림 안에서 온 오류는 상한과 무관하다(게이트는 스트림이 열리기 전에 429로 막는다).
          setStatus({ kind: "error", retryPayload: pending });
        } else if (event.type === "statChange" && pending.kind === "newTurn") {
          const previous = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId))?.stats[event.statId];
          deltas = addStatDelta(deltas, event.statId, previous, event.newValue);
        } else if (event.type === "hiddenStatSignal") {
          hiddenSignal = true;
        } else if (event.type === "done") {
          statRewind = event.statRewind;
        }
        applyStreamEvent(queryClient, roomId, event, {
          kind: pending.kind,
          removedReplyCount,
          onDone: (message) => {
            hasCommitted = true;
            committedMessage = message;
            const archiveKey = imageArchiveKeyToInvalidate(imageArchive, message);
            if (archiveKey) void queryClient.invalidateQueries({ queryKey: archiveKey });
          },
        });
      }
    } catch (error) {
      hasErrored = true;
      wasRejected = isApiError(error);
      // SSE는 뮤테이션이 아니라 `app/AppProviders.tsx`의 MutationCache.onError가 못 본다.
      // 재동의 403을 여기서 잡지 않으면 채팅 4경로에서만 모달이 뜨지 않는다(세션을 다시 조회하면
      // ReconsentModal이 `GET /me`의 플래그로 뜬다 — 전역 MutationCache의 재동의 403 처리와 같은 처리다).
      if (isLegalReconsentRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      }
      // 같은 이유로 세션 소실 401·정지 403도 여기서 세션을 비운다.
      resetSessionIfLost(queryClient, error);
      const sessionEnded = getSessionEndReason(error);
      if (sessionEnded) {
        setStatus({ kind: "error", retryPayload: pending, sessionEnded });
        return;
      }
      // 방을 연 뒤에 작품이 제한된 경우다. 방을 다시 받아 `contentRestricted`를 서버 값으로 맞춘다 — 확인 모달은
      // 띄우지 않는다(429가 아니라 클로버와 무관하다).
      if (isContentRestrictedError(error)) {
        void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
        setStatus({ kind: "error", retryPayload: pending, restricted: true });
        return;
      }
      // 본인인증 전이라 막혔다. 세션을 다시 읽어(SSE 라 전역 MutationCache 가 못 본다) 게이트 상태를 화면과 맞추고,
      // 확인 모달은 띄우지 않는다 — 동의해도 쓸 클로버가 없다.
      if (isIdentityVerificationRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
        setStatus({ kind: "error", retryPayload: pending, identityRequired: true });
        return;
      }
      // 앞 턴이 아직 돌고 있다. 클로버와 무관하므로 확인 모달도 띄우지 않는다.
      if (settleTurnInProgress(queryClient, roomId, error, pending.messagesBeforeEdit)) {
        setStatus({ kind: "error", retryPayload: pending, busy: true });
        return;
      }
      // 동의가 필요하면 배너가 아니라 모달이다. 동의하면 **같은
      // payload로** 재전송한다(`send()`를 다시 부르지 않으므로 낙관적 사용자 메시지가 중복되지
      // 않는다 — `retry()`와 같은 이유로 `openStream`을 직접 부른다).
      // 가격이 바뀌었다는 409 도 같은 길이다 — 저절로 다시 보내지 않고 새 가격으로 보낼지 묻는다. 그만두면 아래 `declined`
      // 배너가 다시 보내기를 열어 두고, 낙관적 사용자 메시지와 재시도 대상은 그대로 남는다.
      const confirmOutcome = canAskCloverConfirm(error, allowance) ? await confirmCloverSpend?.(error) : undefined;
      if (confirmOutcome === "retry") {
        await openStream(pending, allowanceAfterCloverConfirm(error, allowance));
        return;
      }
      setStatus({
        kind: "error",
        retryPayload: pending,
        rateLimit: getChatRateLimit(error),
        // 그만두기는 실패가 아니다. 배너가 이 값으로 문구를 가른다.
        declined: confirmOutcome === "declined",
      });
    } finally {
      setStreamingText("");
      settleTurnStreamEnd(queryClient, roomId, {
        dropped,
        hasCommitted,
        isEdit: pending.payload.kind === "edit",
        wasRejected,
      });
      // 칩·안내는 턴이 확정된 뒤 한 번만 — 스트리밍 도중이나 응답이 커밋되지 않은 턴에는 알리지 않는다.
      // 안내 문장은 여기서 그 턴의 값으로 한 번 만들어 둔다 — 뒤에 값이 바뀌어도 다시 만들지 않는다. 스탯 이름·장면 글은 화면과
      // 같이 작가 매크로를 펼친 글로 읽는다.
      if (hasCommitted && committedMessage) {
        // 수정이 지운 턴의 스탯을 되돌렸으면 캐시의 직전 값은 되돌리기 전 값이라 그 차는 이번 턴의 변화가 아니다 — 재생성과
        // 같은 이유로 칩을 세우지 않는다.
        if (statRewind !== undefined) deltas = {};
        const room = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId));
        turnFeedbackSeqRef.current += 1;
        setTurnFeedback({
          turn: turnFeedbackSeqRef.current,
          roomId,
          messageId: committedMessage.id,
          deltas,
          hiddenSignal,
          announcement: room ? buildRoomTurnAnnouncement(room, { deltas, hiddenSignal }, sceneBeforeTurn) : "",
        });
      }
      if (!hasErrored) setStatus({ kind: "idle" });
      if (pending.kind === "regenerate" && committedMessage) onRegenerated?.(committedMessage);
      if (pending.payload.kind === "edit" && hasCommitted) onEdited?.(statRewind);
    }
  }

  // 보내는 글의 이름 매크로는 낙관적 메시지를 만들기 전에 바꾼다(`expandUserTextForRoom`). 재시도는 이미 바꾼 페이로드를
  // 다시 보내고, 재생성은 글을 보내지 않는다.
  function send(rawText: string, shortcutId?: string): void {
    const text = expandUserTextForRoom(queryClient, roomId, rawText);
    const optimisticMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    addOptimisticUserMessage(queryClient, roomId, optimisticMessage);

    void openStream({ payload: buildSendPayload({ roomId, text, shortcutId }), kind: "newTurn" });
  }

  // 마지막 AI 응답만 새 텍스트로 교체(같은 턴), 새 사용자
  // 메시지를 추가하지 않는다.
  function regenerate(): void {
    if (status.kind === "sending") return;
    void openStream({ payload: buildRegeneratePayload({ roomId }), kind: "regenerate" });
  }

  // openStream이 truncateAndEdit로 그 메시지 이후를 먼저 잘라낸 뒤, 일반 전송과 동일한 스트리밍 흐름을
  // 재실행한다(편집 대상 이후 새 응답을 append) — send()와 달리 낙관적 사용자 메시지를 새로
  // 추가하지 않는다(이미 캐시에 있는 메시지를 truncateAndEdit이 갱신한다).
  function editMessage(messageId: string, rawText: string): void {
    if (status.kind === "sending") return;
    const text = expandUserTextForRoom(queryClient, roomId, rawText);
    void openStream({ payload: buildEditPayload({ roomId, messageId, text }), kind: "newTurn" });
  }

  function retry(): void {
    if (status.kind !== "error") return;
    // 동일 payload로 스트림만 재오픈 — 사용자 메시지를 중복 추가하지 않음(send()를 다시 호출하지 않음).
    // 다만 그 사이 재조회가 낙관적 메시지를 지웠으면 다시 둔다(끝에 같은 글이 있으면 그대로).
    ensureUserMessageForSend(queryClient, roomId, status.retryPayload.payload);
    void openStream(status.retryPayload);
  }

  return { send, retry, regenerate, editMessage, status, policyWarning, streamingText, turnFeedback };
}
