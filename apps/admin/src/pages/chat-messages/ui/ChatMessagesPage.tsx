import { useState } from "react";
import type { components } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { useChatMessagesQuery } from "../api/useChatMessagesQuery";
import type { ChatMessagesCursor } from "../api/keys";
import type { AdminChatMessagesResponse } from "../api/useViewChatMutation";
import { ViewReasonDialog } from "./ViewReasonDialog";

type AdminChatMessageItem = components["schemas"]["AdminChatMessageItem"];

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const ROLE_LABELS: Record<AdminChatMessageItem["role"], string> = {
  user: "사용자",
  assistant: "AI",
};

function nextCursor(page: AdminChatMessagesResponse): ChatMessagesCursor | null {
  return page.beforeCreatedAt && page.beforeId
    ? { beforeCreatedAt: page.beforeCreatedAt, beforeId: page.beforeId }
    : null;
}

function ChatMessageRow({ item }: { item: AdminChatMessageItem }) {
  const isUser = item.role === "user";
  return (
    <li className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}>
      <span className="text-xs font-medium text-muted-foreground">
        {ROLE_LABELS[item.role]} · {DATE_TIME_FORMATTER.format(new Date(item.createdAt))}
      </span>
      {/* 관리자가 남의 대화를 읽는 화면이라 web(MessageBubble)의 `primary` 말풍선을 그대로 옮기지
       * 않는다 — `primary`는 "지금 누를 수 있는 것"과 "지금 내가 한 말"에만 쓰는데, 여기서 admin은
       * 어느 쪽 화자도 아니다. 정렬(사용자 오른쪽/AI 왼쪽)은 두 화면 사용자에게 익숙한 채팅 관습을
       * 그대로 따르되, 색은 둘 다 무채색으로 두고 배경 톤 차이(`secondary` vs `card`+border)로만
       * 구분한다. */}
      <p
        className={cn(
          "max-w-[75%] whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5 text-sm text-foreground",
          isUser ? "bg-secondary" : "border border-border bg-card",
        )}
      >
        {item.content}
      </p>
    </li>
  );
}

type ChatMessagesPageProps = {
  userId: string;
  roomId: string;
};

export function ChatMessagesPage({ userId, roomId }: ChatMessagesPageProps) {
  const navigate = useNavigate();
  const [viewResult, setViewResult] = useState<AdminChatMessagesResponse>();
  const [olderItems, setOlderItems] = useState<AdminChatMessageItem[]>([]);
  const [cursor, setCursor] = useState<ChatMessagesCursor | null>(null);

  const messagesQuery = useChatMessagesQuery(roomId);
  const goToUserDetail = () => void navigate({ to: "/users/$userId", params: { userId } });

  const handleLoadMore = async () => {
    if (!cursor) return;
    try {
      const page = await messagesQuery.fetchPage(cursor);
      setOlderItems((prev) => [...prev, ...page.items]);
      setCursor(nextCursor(page));
    } catch {
      toast.error("메시지를 더 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  if (!viewResult) {
    return (
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
        <Button asChild variant="outline" size="sm" className="self-start">
          <Link to="/users/$userId" params={{ userId }}>
            유저 상세로
          </Link>
        </Button>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">채팅 열람</h1>
        <ViewReasonDialog
          roomId={roomId}
          onCancel={goToUserDetail}
          onConfirmed={(data) => {
            setViewResult(data);
            setCursor(nextCursor(data));
          }}
        />
      </main>
    );
  }

  // techspec §4-5: 서버는 `(created_at, id) DESC`로 준다(최신→과거). "더 보기"로 이어 받는 다음
  // 페이지는 항상 그 이전 페이지의 커서보다 더 과거이므로, 도착 순서대로 이어 붙이기만 해도
  // `[...viewResult.items, ...olderItems]`는 그 자체로 전체가 최신→과거 정렬이다(페이지 경계에서
  // 별도 정렬/병합이 필요 없다). 화면은 "위가 과거, 아래가 최신"으로 보여준다(대화를 실제로 나눈
  // 순서 그대로 위→아래로 읽히는 게 관리자에게도 익숙한 채팅 UI 관습이라 그대로 따름) — 그래서
  // 렌더 직전에 한 번만 뒤집는다. "더 보기"는 과거를 불러오므로 목록 위쪽에 둔다.
  const displayItems = [...viewResult.items, ...olderItems].reverse();

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/users/$userId" params={{ userId }}>
          유저 상세로
        </Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">채팅 열람</h1>

      {displayItems.length === 0 ? (
        <p className="text-sm text-muted-foreground">메시지가 없어요.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {cursor && (
            <div className="flex justify-center">
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-disabled={messagesQuery.isFetching}
                onClick={() => {
                  if (!messagesQuery.isFetching) void handleLoadMore();
                }}
                className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
              >
                {messagesQuery.isFetching ? "불러오는 중..." : "더 보기"}
              </Button>
            </div>
          )}

          <ol className="flex flex-col gap-3">
            {displayItems.map((item) => (
              <ChatMessageRow key={item.id} item={item} />
            ))}
          </ol>
        </div>
      )}
    </main>
  );
}
