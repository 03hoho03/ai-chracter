import { useEffect, useRef, useState } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@ai-character-chat/ui/components/avatar";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ArrowLeft, History, RotateCw, Send, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import type { Shortcut } from "@/entities/chat-room";
import {
  EndingDivider,
  MessageBubble,
  StatGaugePanel,
  TypingIndicator,
  shouldShowSuggestedReplies,
  useAcknowledgeVersionUpgradeMutation,
  useChatRoomQuery,
  useDeleteMessageMutation,
} from "@/entities/chat-room";
import { useContentDetailQuery } from "@/entities/content";
import { useSendMessage } from "@/features/send-message";
import { ShortcutAutocomplete } from "@/features/shortcut-autocomplete";

import { ChatMorePanel } from "./ChatMorePanel";
import { ChatMoreSidebar } from "./ChatMoreSidebar";

// techspec-chat-character.md, techspec-chat-story.md, techspec-chat-common.md §1/§5 — US-055/060:
// 대화방 상세 조회 + 메시지 전송/스트리밍 표시 + 오류·정책경고 배너를 갖춘 캐릭터/스토리 공용 대화 화면.
// 스토리 챗은 room.contentSnapshot이 있을 때만 스탯 게이지가 추가로 붙는다(캐릭터 챗은 undefined).
export function ChatRoomView({ roomId }: { roomId: string }) {
  const roomQuery = useChatRoomQuery(roomId);
  const room = roomQuery.data;
  const contentQuery = useContentDetailQuery(room?.contentId ?? "", room !== undefined);
  const content = contentQuery.data;

  const characterId = room?.contentType === "character" ? room.contentId : undefined;
  const { send, retry, regenerate, editMessage, status, policyWarning, streamingText } = useSendMessage(
    roomId,
    characterId,
  );
  const isSending = status.kind === "sending";
  const deleteMessageMutation = useDeleteMessageMutation(roomId);
  const [text, setText] = useState("");
  const [editingMessageId, setEditingMessageId] = useState<string>();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // US-079, techspec-content-versioning.md §4 — 배너는 방 진입 시 1회만 노출한다. versionAutoUpgraded는
  // acknowledge 뮤테이션 성공 즉시 캐시에서 false로 꺼지므로, 그 값을 직접 렌더링 조건으로 쓰면 배너가
  // 뜨자마자 사라진다 — 로컬 state로 "봤다"는 사실을 분리해서 들고 있는다. room이 비동기로 로드되므로
  // useEffectOnce 대신 usePlayContent와 동일한 ref 가드+useEffect 패턴을 쓴다.
  const [isVersionUpgradeBannerVisible, setIsVersionUpgradeBannerVisible] = useState(false);
  const acknowledgeVersionUpgradeMutation = useAcknowledgeVersionUpgradeMutation(roomId);
  const versionUpgradeAcknowledgedRef = useRef(false);
  useEffect(() => {
    if (versionUpgradeAcknowledgedRef.current || !room) return;
    versionUpgradeAcknowledgedRef.current = true;
    if (room.versionAutoUpgraded) {
      setIsVersionUpgradeBannerVisible(true);
      acknowledgeVersionUpgradeMutation.mutate();
    }
  }, [room]);

  function handleDeleteMessage(messageId: string) {
    deleteMessageMutation.mutate(messageId, {
      onError: () => toast.error("메시지 삭제에 실패했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [room?.messages.length, streamingText]);

  useEffect(() => {
    if (policyWarning) inputRef.current?.focus();
  }, [policyWarning]);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || isSending) return;
    send(trimmed);
    setText("");
  }

  function handleShortcutSelect(shortcut: Shortcut) {
    if (isSending) return;
    send(shortcut.prompt, shortcut.id);
    setText("");
  }

  function handleSuggestedReplyClick(reply: string) {
    if (isSending) return;
    send(reply);
  }

  if (roomQuery.isPending) {
    return (
      <div className="flex h-below-header flex-col">
        <ChatRoomSkeleton />
      </div>
    );
  }

  if (roomQuery.isError || !room) {
    return (
      <div className="flex h-below-header items-center justify-center px-4 sm:px-6">
        <p className="text-sm text-destructive-text">대화방을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      </div>
    );
  }

  return (
    <div className="flex h-below-header flex-col">
      {/* border-b를 <header>가 아니라 안쪽 컬럼 div에 건다 — 뷰포트를 가로지르는 선은 전역 헤더의
          border-b 하나뿐이어야 한다(DESIGN.md §Navigation "크롬은 sticky 헤더 하나뿐이다"). <header>에
          걸면 이 선만 전폭이 되어 바로 아래 StatGaugePanel·버전 배너의 border-b, 입력창의 border-t와
          길이가 크게 벌어진다. 옮기면 선이 뷰포트가 아니라 컬럼 경계를 따른다 — 1425px 실측에서
          전역 헤더 1425 / 채팅 헤더 1024 / 입력창 1024px다.
          단 "전부 같은 길이"가 되는 건 사이드바가 닫혀 있을 때뿐이다: 열면 채팅 헤더 선은 행 전체를
          (1024), 아래 선들은 채팅 컬럼만(736) 덮는다. 헤더가 채팅 컬럼과 사이드바 **둘 다** 위에
          있으니 이건 맞는 동작이다 — 옮기기 전에는 같은 상태에서 1425 vs 736이었다. */}
      <header className="shrink-0">
        <div className="mx-auto flex max-w-5xl items-center gap-3 border-b border-border px-4 sm:px-6 py-3">
          <Button variant="ghost" size="icon" aria-label="뒤로가기" onClick={() => window.history.back()}>
            <ArrowLeft aria-hidden className="size-4" />
          </Button>
          <Avatar>
            <AvatarImage src={content?.thumbnailUrl ?? undefined} alt="" />
            <AvatarFallback>{content?.name.slice(0, 1) ?? "?"}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm font-semibold text-foreground">{content?.name ?? "대화"}</span>
            <span className="truncate text-xs text-muted-foreground">{room.name}</span>
          </div>
          <ChatMorePanel
            roomId={roomId}
            contentType={room.contentType}
            startingSetupId={room.contentSnapshot?.pinnedStartingSetupId}
            characterId={characterId}
          />
        </div>
      </header>

      {/* US-004 — 더보기 사이드바는 채팅 헤더 아래부터 바닥까지 채우고 채팅 컬럼과 폭을 나눠 갖는다.
          min-h-0/min-w-0이 없으면 flex 아이템의 기본 min-*:auto가 메시지 영역의 스크롤과 축소를 막는다.
          max-w-5xl은 셸이 아니라 이 행에 건다 — 채팅 컬럼이 중앙 정렬된 행의 첫 flex 아이템이라
          사이드바를 여닫아도(오른쪽에서만 폭을 가져가므로) 좌측 콘텐츠 시작점이 움직이지 않는다.
          w-full이 없으면 flex 컬럼 자식의 auto 마진 때문에 stretch가 꺼져 폭이 shrink-to-fit으로
          붕괴한다. */}
      <div className="mx-auto flex w-full min-h-0 max-w-5xl flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          {isVersionUpgradeBannerVisible && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border bg-secondary/50 px-4 sm:px-6 py-2.5 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
              <History aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">최신 버전으로 자동 전환되었어요.</span>
            </div>
          )}

          {room.contentSnapshot && <StatGaugePanel stats={room.contentSnapshot.stats} values={room.stats} />}

          <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
            <div className="flex flex-col gap-3">
              {room.messages.map((message, index) => {
                const isLastMessage = index === room.messages.length - 1;
                return (
                  <MessageBubble
                    key={message.id}
                    message={message}
                    disabled={isSending}
                    isEditing={editingMessageId === message.id}
                    canRegenerate={isLastMessage && message.role === "assistant" && room.messages.length >= 2}
                    onRegenerate={isLastMessage && message.role === "assistant" ? regenerate : undefined}
                    onStartEdit={message.role === "user" ? () => setEditingMessageId(message.id) : undefined}
                    onCancelEdit={() => setEditingMessageId(undefined)}
                    onSaveEdit={(newText) => {
                      editMessage(message.id, newText);
                      setEditingMessageId(undefined);
                    }}
                    onDelete={() => handleDeleteMessage(message.id)}
                  />
                );
              })}

              {room.endingStatus.reached && !!room.endingStatus.epilogue && (
                <>
                  <EndingDivider
                    endingName={room.contentSnapshot?.endings.find((ending) => ending.id === room.endingStatus.endingId)?.name}
                  />
                  <MessageBubble
                    message={{ id: "ending-epilogue", role: "assistant", content: room.endingStatus.epilogue, createdAt: "" }}
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
                <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5">
                  <span className="text-xs text-destructive-text">응답 생성에 실패했습니다 · 다시 시도</span>
                  <Button variant="destructive" size="sm" onClick={retry}>
                    <RotateCw aria-hidden className="size-3.5" />
                    다시 시도
                  </Button>
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
            {/* 첫 턴 전송을 시작한 순간부터 감춘다 — turnCount는 스트림 종료(done)에야 오르지만,
                사용자 메시지가 전송 즉시 캐시에 낙관적으로 추가되므로 hasUserMessage 항이 스트리밍
                구간을 덮는다. 전송이 실패해도 그 메시지는 캐시에 남으므로(FR-88) 칩은 되살아나지
                않는다 — 재시도는 오류 배너의 "다시 시도"가 담당한다. */}
            {room.contentSnapshot &&
              shouldShowSuggestedReplies(
                room.contentSnapshot.suggestedReplies,
                room.turnCount,
                room.messages.some((message) => message.role === "user"),
              ) && (
                <div className="mb-2 flex gap-2 overflow-x-auto pb-0.5">
                  {room.contentSnapshot.suggestedReplies.map((reply) => (
                    <Button
                      key={reply}
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={isSending}
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
                {room.contentSnapshot && text.startsWith("/") && (
                  <ShortcutAutocomplete
                    shortcuts={room.contentSnapshot.shortcuts}
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

        <ChatMoreSidebar
          roomId={roomId}
          contentType={room.contentType}
          startingSetupId={room.contentSnapshot?.pinnedStartingSetupId}
          characterId={characterId}
        />
      </div>
    </div>
  );
}

function ChatRoomSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 sm:px-6 py-4">
      <div className="h-16 w-2/3 animate-pulse rounded-lg bg-muted" />
      <div className="ml-auto h-10 w-1/2 animate-pulse rounded-lg bg-muted" />
      <div className="h-12 w-3/5 animate-pulse rounded-lg bg-muted" />
    </div>
  );
}
