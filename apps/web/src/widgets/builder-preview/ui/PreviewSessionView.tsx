import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ChevronDown, RotateCw, Send, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { DEFAULT_CHAT_MODEL, isPremiumChatModel, useChatModelsQuery, type ChatModelId } from "@/entities/chat-model";
import type { PreviewShortcut, PreviewStartPayload } from "@/entities/preview-session";
import {
  AuthorMacroNamesProvider,
  EndingDivider,
  expandStoryScene,
  hasSceneText,
  isAuthorOpeningMessage,
  isAuthorTextMessage,
  MediaTagImagesProvider,
  MessageBubble,
  RateLimitNotice,
  selectCurrentScene,
  StatGaugePanel,
  TypingIndicator,
  shouldShowSuggestedReplies,
} from "@/entities/chat-room";
import {
  CloverBalance,
  isCloverInsufficient,
  shouldShowCloverBalance,
  useCloverBalanceQuery,
  useCloverPricingQuery,
} from "@/entities/clover";
import { IdentityRequiredNotice } from "@/entities/identity";
import type { MediaTagImages } from "@/entities/media-book";
import { usePersonasQuery } from "@/entities/persona";
import { buildPreviewStartState, usePreviewSessionQuery, useStartPreviewMutation } from "@/entities/preview-session";
import { getSessionEndReason, SessionEndedNotice, useSessionQuery, type SessionEndReason } from "@/entities/session";
import { PreviewCloseHeader } from "@/features/build-common";
import { useConfirmCloverSpend } from "@/features/confirm-clover-spend";
import { NarrationMarkerButton } from "@/features/insert-narration-marker";
import {
  CHAT_MODEL_NOT_ALLOWED_MESSAGE,
  invalidateChatModelAccess,
  isChatModelNotAllowedError,
} from "@/features/select-chat-model";
import { usePreviewSendMessage } from "@/features/preview-chat";
import { ShortcutAutocomplete } from "@/features/shortcut-autocomplete";
import { expandAuthorMacros } from "@/shared/lib/text/authorMacros";

import { previewAuthorMacroNames } from "../model/previewAuthorMacroNames";
import {
  isPreviewModelSelectable,
  previewDisplayModel,
  previewStartQuery,
  previewTurnCost,
} from "../model/previewChatModel";
import { previewConfirmTurnCost } from "../model/previewConfirmTurnCost";
import { previewEmptyHint } from "../model/previewEmptyHint";
import { previewPersonaLabel } from "../model/previewPersonaLabel";
import { PreviewChatModelModal } from "./PreviewChatModelModal";

type PreviewSessionViewProps = {
  getPayload: () => PreviewStartPayload;
  /** 첫 메시지 속 미디어 북 태그를 그릴 칸 그림(`{칸 id: 그림}`). 미디어 북이 없는 빌더(캐릭터)는 넘기지 않는다. */
  getMediaBookImages?: () => MediaTagImages;
  onClose?: () => void;
};

// 빌더 어디서든 열리는 테스트 대화 화면. 실제 채팅의 순수
// 프레젠테이션 컴포넌트(메시지 리스트/스탯 게이지)는 entities/chat-room, 단축어 자동완성은
// features/shortcut-autocomplete에서 그대로 재사용하되, 데이터 레이어(entities/preview-session)는
// 완전히 분리되어 있다 — 스탯/키워드북/단축어/엔딩 판정은 실제 채팅과 동일한 서버 로직이
// 그대로 처리하고 이 화면은 그 결과만 반영한다. getPayload는 호출 시점의 최신 폼 값
// (formToServer(getValues()))을 돌려주는 함수로, "미리보기 초기화"도 이 함수를 다시 호출해
// 최신 폼 값 기준 새 세션을 연다.
//
// 서버 세션은 마운트가 아니라 첫 전송 때 생긴다. 그 전까지는
// buildPreviewStartState로 계산한 로컬 플레이스홀더만 그린다(BE의 _build_preview_start_state를
// 그대로 재현하므로 화면은 세션이 있을 때와 같다). 입력창·단축어·추천답변 세 전송 경로가 전부
// ensurePreviewSession()을 거쳐 세션을 보장한 뒤에야 usePreviewSendMessage의 send()를 부른다.
export function PreviewSessionView({ getPayload, getMediaBookImages, onClose }: PreviewSessionViewProps) {
  const startMutation = useStartPreviewMutation();
  const queryClient = useQueryClient();
  const [previewSessionId, setPreviewSessionId] = useState<string>();
  const stateQuery = usePreviewSessionQuery(previewSessionId);
  // usePreviewSessionQuery는 enabled:false라 캐시는 오직
  // useStartPreviewMutation의 성공 콜백으로만 채워진다. 지연 시작 이후 첫 전송 전에는 그 캐시가
  // 비어 있으므로, 세션 id 없이 계산한 로컬 상태로 대신한다 — 안 그러면 첫 전송 전까지 영구
  // 스켈레톤이 된다.
  // 세션이 생긴 뒤에는 폼을 다시 변환하지 않는다 — 스트리밍 글자마다 이 화면이 다시 그려진다.
  const state = stateQuery.data ?? buildPreviewStartState(undefined, getPayload(), getMediaBookImages?.());
  // 미리보기 턴은 작가의 기본 프로필을 조용히 쓴다. 무엇이 들어가는지 입력창
  // 위에 한 줄로 보인다. `isSuccess`만 넘기는 건 재조회 실패(옛 data가 남은 error)에도 숨기기 위해서다.
  const personasQuery = usePersonasQuery();
  const personaList = personasQuery.isSuccess ? personasQuery.data : undefined;
  const personaCaption = previewPersonaLabel(personaList);
  // 작가 글(첫 메시지·에필로그·칩·단축어·스탯 이름)의 `{{user}}`·`{{char}}` 를 서버의 미리보기 프롬프트와 같은 이름으로
  // 바꿔 보인다. 작품 쪽 값은 세션 상태의 것이라 세션 도중 폼에서 이름을 고쳐도 서버(시작 때 페이로드)와 갈리지 않는다.
  const macroNames = previewAuthorMacroNames(state.authorNameSource, state.contentType, personaList);
  const expandForPreview = (text: string) => expandAuthorMacros(text, macroNames);
  const emptyHint = previewEmptyHint(state.contentType, state.messages);
  // 장면 헤더를 켠 초안은 실제 방과 같은 규칙으로 지금 장면을 고른다. 세션 전에도 첫 장면이 보여 작가가 바로 확인한다.
  const scene = state.sceneHeaderEnabled
    ? expandStoryScene(selectCurrentScene(state.messages, state.initialScene), expandForPreview)
    : undefined;

  // 고른 모델은 이 화면의 지역 상태다 — 빌더를 떠나면 기본 모델로 돌아온다(확인은 고른 그 순간의 동의라 다음 방문에
  // 확인 없이 상위 모델 가격이 나가지 않게 한다). 화면이 말하는 모델은 저장하지 않고 세션의 기능 목록으로 매번 정한다.
  const [chosenModelId, setChosenModelId] = useState<ChatModelId>(DEFAULT_CHAT_MODEL);
  const { data: me } = useSessionQuery();
  const displayModelId = previewDisplayModel(me?.enabledFeatures, chosenModelId);
  const models = useChatModelsQuery().data;
  // 기능이 꺼진 계정에는 칩이 없다. 목록이 아직 없으면 이름을 모르므로 칩을 미룬다 — 기본 모델 이름을 지어 넣지 않는다.
  const modelChipName = isPreviewModelSelectable(me?.enabledFeatures)
    ? models?.find((model) => model.id === displayModelId)?.name
    : undefined;
  // 미리보기도 채팅 4경로와 **같은 게이트**를 지나므로 같은
  // 확인이 필요하다. 트리거를 위젯이 만들어 넘기는 이유와 단가를 여기서 묶는 이유는
  // `ChatRoomView`와 같다 — 한 턴 단가다. 방이 없어 방 응답의 가격이 없으므로 지금 답을 쓰는 모델의 가격을 모델 목록에서
  // 읽는다. 하루 한 번 확인은 기본 모델 턴에서만 오므로 실제로는 기본 모델 가격이 실린다. 목록을 못 받았으면 확인 문구가
  // 숫자 없이 말한다.
  const confirmCloverSpend = useConfirmCloverSpend();
  const turnCost = previewTurnCost(models, displayModelId);
  // 가격표를 지켜보게 둔다 — 보내는 요청이 이 캐시에서 가격 버전을 읽는데, 빌더는 전역 헤더(평소 가격표를 지켜보는 자리)를
  // 그리지 않아 이것이 없으면 새로고침 직후엔 캐시가 비어 있고 한동안 지나면 지워져 버전 없이 나간다. 값은 여기서 쓰지 않는다.
  useCloverPricingQuery();
  // 잔량은 대화방 입력 바와 같은 판정이다 — 상위 모델은 첫 턴부터 턴마다 깎이므로 언제나, 기본 모델은 무료분을 쓴 뒤나
  // 부족할 때만. 세션을 잃은 뒤에는 내린다(옛 잔액이 캐시에 남는다).
  const { data: clover } = useCloverBalanceQuery();
  const cloverBalance = clover?.balance ?? 0;
  const isCloverShort = turnCost !== undefined && isCloverInsufficient(cloverBalance, turnCost);
  const shouldShowClover =
    clover !== undefined &&
    me !== undefined &&
    shouldShowCloverBalance({
      spendConfirmedToday: clover.spendConfirmedToday,
      hasCloverShortage: isCloverShort,
      chargesEveryTurn: isPremiumChatModel(displayModelId),
    });
  const { send, status, policyWarning, streamingText } = usePreviewSendMessage(
    async (error) =>
      // 금액은 렌더 때의 `turnCost` 가 아니라 요청 시점의 캐시에서 읽는다(가격 바뀜이면 모델 목록을 다시 받은 뒤) — 가격 확인
      // 뒤 재전송이 받는 하루 한 번 확인이 옛 가격을 말하지 않게(`previewConfirmTurnCost`).
      // 미리보기도 `"chat"`이다 — 게이트가 채팅 4경로에 같은 일일 버킷을 쓰므로 자정 사유가 참이다.
      confirmCloverSpend(error, await previewConfirmTurnCost(queryClient, error, displayModelId), "chat"),
    macroNames,
  );
  const isSending = status.kind === "sending";
  const [text, setText] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  // 미리보기 세션을 만드는 요청이 세션이 끝나 거절됐을 때의 까닭. 전송이 거절됐을 때(`status.sessionEnded`)와 같은 안내를 띄운다.
  const [startSessionEnded, setStartSessionEnded] = useState<SessionEndReason>();
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // mutate()의 콜백 인자(onSuccess) 대신 mutateAsync()를 쓰고, 로딩 상태도 startMutation.isPending이
  // 아니라 로컬 isStarting으로 직접 관리한다 — apps/web/CLAUDE.md "마운트 시 뮤테이션은
  // mutateAsync+await+로컬 로딩 state"와 같은 이유(widgets/content-detail/lib/usePlayContent.ts의
  // start()도 동일)로, 이 함수는 이제 마운트가 아니라 첫 전송 시점에 호출되지만 StrictMode
  // 마운트→언마운트→재마운트 취약성은 뮤테이션 훅 자체의 성질이라 여전히 적용된다.
  //
  // `onModelNotAllowed` 는 상위 모델 허용이 그 사이 꺼져 시작이 거절됐을 때만 불린다 — 입력창에서 보낸 글을 되돌려 놓는 데 쓴다.
  async function startPreview(onModelNotAllowed?: () => void): Promise<string | undefined> {
    setIsStarting(true);
    setStartSessionEnded(undefined);
    try {
      const nextState = await startMutation.mutateAsync({
        payload: getPayload(),
        query: previewStartQuery(displayModelId),
        mediaBookImages: getMediaBookImages?.(),
      });
      setPreviewSessionId(nextState.previewSessionId);
      return nextState.previewSessionId;
    } catch (error) {
      // 칩이 보이던 사이 상위 모델 허용이 꺼졌다. 기본 모델로 되돌리고 세션·모델 목록을 다시 읽어 칩을 거둔다. 다시 보내면
      // 기본 모델로 열리므로 이용자가 쓴 글은 지우지 않고 입력창에 되돌려 둔다.
      if (isChatModelNotAllowedError(error)) {
        toast.error(CHAT_MODEL_NOT_ALLOWED_MESSAGE);
        setChosenModelId(DEFAULT_CHAT_MODEL);
        invalidateChatModelAccess(queryClient);
        onModelNotAllowed?.();
        return undefined;
      }
      // 로그인이 풀렸거나 정지돼 거절된 것이면 "잠시 후 다시 시도"가 거짓이다(기다려도 같은 거절) — 첫 전송이 이 요청에서
      // 막혀도 세션이 있을 때의 전송 거절과 같은 안내(다시 로그인 / 문의처)를 띄운다.
      const sessionEnded = getSessionEndReason(error);
      if (sessionEnded) setStartSessionEnded(sessionEnded);
      else toast.error("미리보기 세션을 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
      return undefined;
    } finally {
      setIsStarting(false);
    }
  }

  // 세 전송 경로(입력창·단축어·추천답변) 공통 "세션 보장" 함수 — 이미 세션이 있으면 그대로 쓰고,
  // 없으면 이 시점의 getPayload()로 새로 만든다.
  async function ensurePreviewSession(onModelNotAllowed?: () => void): Promise<string | undefined> {
    if (previewSessionId) return previewSessionId;
    return startPreview(onModelNotAllowed);
  }

  // 모델을 바꾸면 세션 id 만 비운다 — 화면은 곧바로 로컬 시작 상태(처음 화면)가 되고, 새 세션은 다음 전송이 고른 모델로
  // 연다. 모달 안에서 바로 열지 않는 것은 시작 실패(권한·세션 끝남)를 지금처럼 전송 자리 한 곳에서만 다루려는 것이다.
  async function handleChooseModel() {
    if (isSending || isStarting) return;
    const nextModelId = await PreviewChatModelModal.call({
      currentModelId: displayModelId,
      hasSession: previewSessionId !== undefined,
    });
    if (nextModelId === undefined || nextModelId === displayModelId) return;
    setChosenModelId(nextModelId);
    setPreviewSessionId(undefined);
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [state.messages.length, streamingText]);

  // ensurePreviewSession()이 돌려준 id를 send()에 직접 태운다 — usePreviewSendMessage가 훅 레벨
  // 파라미터 대신 호출마다 id를 받는 이유(features/preview-chat/model/usePreviewSendMessage.ts 참고)가
  // 바로 이 지점: 세션을 막 만든 직후엔 컴포넌트가 아직 그 id로 재렌더되지 않아 previewSessionId
  // state를 참조하면 stale한 undefined를 잡는다.
  async function sendWithSession(content: string, shortcutId?: string, onModelNotAllowed?: () => void) {
    const id = await ensurePreviewSession(onModelNotAllowed);
    if (!id) return;
    void send(id, content, shortcutId);
  }

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || isSending || isStarting) return;
    setText("");
    // 기다리는 사이 새로 쓴 글이 있으면 덮지 않는다.
    void sendWithSession(trimmed, undefined, () => setText((current) => (current === "" ? text : current)));
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

  // no-nested-ternary — 갈래(세션 끝남/레이트리밋/본인인증/거절/실패)를 렌더 전에 미리 갈라 둔다.
  let errorNotice: ReactNode = null;
  const sessionEnded = startSessionEnded ?? (status.kind === "error" ? status.sessionEnded : undefined);
  // 레이트리밋·본인인증·그만둠·실패는 그 세션에 보낸 턴의 결과다. 모델을 바꾸면 세션 id 가 비고 대화가 처음으로 돌아가므로
  // 앞 세션의 결과를 남기지 않는다 — 남기면 막히지 않은 새 모델 위에 옛 배너가 남고, 레이트리밋 문구는 새 모델로 다시 골라져
  // 거짓이 된다. 세션 끝남은 세션이 아니라 로그인의 상태라 위에서 그대로 보인다.
  const sendError = status.kind === "error" && previewSessionId !== undefined ? status : undefined;
  if (sessionEnded) {
    // 응답 생성이 실패한 것이 아니라 로그인이 풀렸거나 정지된 것이다.
    errorNotice = <SessionEndedNotice reason={sessionEnded} />;
  } else if (sendError) {
    if (sendError.rateLimit) {
      // 상위 모델 미리보기에는 돌아올 무료 한도가 없어 자정 약속을 하지 않는 문구로 간다.
      errorNotice = (
        <RateLimitNotice
          rateLimit={sendError.rateLimit}
          surface={isPremiumChatModel(displayModelId) ? "premiumPreview" : "preview"}
        />
      );
    } else if (sendError.identityRequired) {
      errorNotice = <IdentityRequiredNotice reason="free-rewards" dailyFreeChatTurns={me?.dailyFreeChatTurns} />;
    } else if (sendError.declined) {
      // 확인 모달에서 그만둔 것은 실패가 아니라 사용자의 선택이라
      // `destructive`도 `role="alert"`도 쓰지 않는다(경고할 일이 없다).
      errorNotice = (
        <div className="flex items-center gap-2 rounded-lg border border-border px-3.5 py-2.5">
          <span className="text-xs text-muted-foreground">클로버를 쓰지 않았어요.</span>
        </div>
      );
    } else {
      errorNotice = (
        <div role="alert" className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3.5 py-2.5">
          <span className="text-xs break-keep text-destructive-text">응답 생성에 실패했습니다.</span>
        </div>
      );
    }
  }

  return (
    <div className="flex h-below-header flex-col">
      {/* `__root` 가 아니라 여기 마운트한다 — 루트가 이 위젯을 import 하면 빌더 미리보기까지 메인 청크로 끌려온다(대화방
          모델 모달과 같은 이유). 여는 곳은 이 화면의 모델 칩 하나뿐이다. */}
      <PreviewChatModelModal />
      <PreviewCloseHeader
        title="미리보기"
        onClose={onClose}
        action={
          <Button variant="outline" size="sm" onClick={() => void startPreview()} disabled={isStarting}>
            <RotateCw aria-hidden className="size-3.5" />
            미리보기 초기화
          </Button>
        }
      />

      <div className="mx-auto flex w-full min-h-0 max-w-5xl flex-1 flex-col">
        {(state.statDefs.length > 0 || hasSceneText(scene)) && (
          <StatGaugePanel
            stats={state.statDefs.map((stat) => ({
              ...stat,
              name: expandForPreview(stat.name),
              unit: stat.unit === undefined ? undefined : expandForPreview(stat.unit),
              playerDescription:
                stat.playerDescription === undefined ? undefined : expandForPreview(stat.playerDescription),
            }))}
            values={state.stats}
            scene={scene}
            hiddenStatIds={new Set(state.statDefs.filter((stat) => stat.hiddenFromPlayer).map((stat) => stat.id))}
          />
        )}

        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
          {/* 메시지 사이 gap-6(24px)은 한 메시지 안 문단 간격(12px)의 두 배다. 상자 없는 산문이 한 컬럼에 흐르므로
              같은 값이면 메시지 경계와 문단 경계가 구분되지 않는다. */}
          <div className="flex flex-col gap-6">
            {/* 보이는 글이 없는 첫 화면은 빈 열이라 무엇이 여기 나올지, 미리보기가 무엇을 보는지 알려 준다. */}
            {emptyHint !== undefined && (
              <p className="mx-auto max-w-sm py-8 text-center text-sm break-keep text-muted-foreground">{emptyHint}</p>
            )}
            {/* 스토리 첫 메시지는 작성자 글이라 글 속 미디어 북 태그를 그림으로 그린다(채팅방과 같은 규칙). */}
            {/* 첫 메시지(캐릭터 인사말 포함)는 작성자 글이라 이름 매크로도 바꾼다. */}
            {state.messages.map((message, index) => {
              const bubble = isAuthorOpeningMessage({ index, role: message.role, contentType: state.contentType }) ? (
                <MediaTagImagesProvider images={state.openingMediaTagImages}>
                  <MessageBubble message={message} />
                </MediaTagImagesProvider>
              ) : (
                <MessageBubble message={message} />
              );
              return isAuthorTextMessage({ index, role: message.role }) ? (
                <AuthorMacroNamesProvider key={message.id} names={macroNames}>
                  {bubble}
                </AuthorMacroNamesProvider>
              ) : (
                <Fragment key={message.id}>{bubble}</Fragment>
              );
            })}

            {state.endingStatus.reached && !!state.endingStatus.epilogue && (
              <>
                <EndingDivider />
                <AuthorMacroNamesProvider names={macroNames}>
                  <MediaTagImagesProvider images={state.endingStatus.mediaTagImages ?? {}}>
                    <MessageBubble
                      message={{ id: "ending-epilogue", role: "assistant", content: state.endingStatus.epilogue, createdAt: "" }}
                    />
                  </MediaTagImagesProvider>
                </AuthorMacroNamesProvider>
              </>
            )}

            {isSending &&
              (streamingText ? (
                <MessageBubble message={{ id: "streaming", role: "assistant", content: streamingText, createdAt: "" }} />
              ) : (
                <TypingIndicator />
              ))}

            {errorNotice}

            {/* 오류 배너(위)는 이산적 실패라 assertive + 조건부 마운트, 이 경고는 메시지와 공존하는
                정보라 polite + 항상 마운트다 — polite는 조건부 마운트에서 announce 여부가 갈린다는
                것이 업계 통설이고, 이 저장소의 polite 3곳(MyWorksPage.tsx:507 등)도 전부 항상
                마운트다. */}
            <div
              aria-live="polite"
              className={policyWarning ? "flex items-center gap-2 rounded-lg border border-border bg-secondary/50 px-3.5 py-2.5" : "sr-only"}
            >
              <TriangleAlert aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              <span className="text-xs break-keep text-muted-foreground">{policyWarning}</span>
            </div>

            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-border bg-background px-4 sm:px-6 py-3">
          {/* 헤더(`PreviewCloseHeader`)가 아니라 여기인 이유: 헤더 행은 `h-8` 고정 한 줄이라 360px에서
              `미리보기 초기화` 옆에 두면 "대화 프로필:…"로 말줄임돼 이름이 통째로 안 보였다(실측). 입력창 위는 전체 폭을
              쓰고, 작가가 말을 거는 바로 그 자리에서 "누구로 대화하는지"를 읽는다. */}
          {/* 모델 칩과 클로버 잔량도 새 줄을 만들지 않고 이 캡션 줄에 든다(칩 왼쪽 · 잔량 오른쪽 — 대화방 좁은 화면의 입력 바
              위 줄과 같은 문법). 머리 줄이 아닌 이유는 위 캡션과 같다: 2단 빌더의 미리보기 열은 폰보다 좁다. */}
          {(modelChipName !== undefined || personaCaption !== undefined || shouldShowClover) && (
            <div className="mb-2 flex items-center gap-2">
              {modelChipName !== undefined && (
                // 대화방 모델 칩과 같은 모양·같은 접근 이름 조립("AI 모델 {이름}, 바꾸기"). 전송 중에는 세션이 바뀌면
                // 안 되므로 막되, 누른 칩에서 포커스가 빠지지 않게 `aria-disabled` 로 막는다.
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-haspopup="dialog"
                  aria-disabled={isSending || isStarting}
                  onClick={() => void handleChooseModel()}
                  className="relative max-w-40 shrink-0 rounded-full text-muted-foreground aria-disabled:opacity-65 pointer-coarse:after:absolute pointer-coarse:after:inset-x-0 pointer-coarse:after:-inset-y-1"
                >
                  <span className="sr-only">AI 모델 </span>
                  <span className="min-w-0 truncate">{modelChipName}</span>
                  <span className="sr-only">, 바꾸기</span>
                  <ChevronDown data-icon="inline-end" aria-hidden />
                </Button>
              )}
              {personaCaption !== undefined && (
                <p className="min-w-0 flex-1 text-xs break-words break-keep text-muted-foreground">{personaCaption}</p>
              )}
              {shouldShowClover && (
                <CloverBalance balance={cloverBalance} isInsufficient={isCloverShort} className="ml-auto shrink-0" />
              )}
            </div>
          )}
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
                  {expandForPreview(reply)}
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
                  shortcuts={state.shortcuts.map((shortcut) => ({
                    ...shortcut,
                    name: expandForPreview(shortcut.name),
                    description: expandForPreview(shortcut.description),
                  }))}
                  query={text.slice(1)}
                  onSelect={handleShortcutSelect}
                />
              )}
            </div>
            <NarrationMarkerButton textareaRef={inputRef} value={text} onValueChange={setText} disabled={isSending} />
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
