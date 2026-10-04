import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { toast } from "sonner";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";

import { useChatMessagesPager } from "../api/useChatMessagesPager";
import type { ChatMessagesCursor } from "../api/keys";
import type {
  AdminChatMessageItem,
  AdminChatMessagesResponse,
  AdminChatRoomView,
} from "../api/useViewChatMutation";
import { ViewReasonDialog } from "./ViewReasonDialog";

const ROLE_LABELS: Record<AdminChatMessageItem["role"], string> = {
  user: "사용자",
  assistant: "AI",
};

const SUMMARY_SOURCE_LABELS: Record<NonNullable<AdminChatRoomView["memorySummary"]>["source"], string> = {
  auto: "AI 요약",
  user: "사용자가 고친 요약",
};

type ChatMessagesPageProps = {
  userId: string;
  roomId: string;
};

export function ChatMessagesPage({ userId, roomId }: ChatMessagesPageProps) {
  useDocumentTitle("채팅 열람");
  const navigate = useNavigate();
  // 열람 응답(기억 포함)과 더보기로 이어 받은 메시지를 따로 든다 — 더보기 응답에는 기억이 없으므로 합쳐 두면
  // 첫 응답의 기억을 덮을 수 있다.
  const [viewResult, setViewResult] = useState<AdminChatRoomView>();
  const [olderItems, setOlderItems] = useState<AdminChatMessageItem[]>([]);
  const [cursor, setCursor] = useState<ChatMessagesCursor>();

  const messagesPager = useChatMessagesPager(roomId);
  const handleCancel = () => void navigate({ to: "/users/$userId", params: { userId } });

  const handleLoadMore = async () => {
    if (!cursor) return;
    try {
      const page = await messagesPager.fetchPage(cursor);
      setOlderItems((prev) => [...prev, ...page.items]);
      setCursor(nextCursor(page));
    } catch {
      toast.error("메시지를 더 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  if (!viewResult) {
    return (
      <PageContainer>
        <ChatMessagesHeader userId={userId} />
        <DetailLayout actions={null}>
          <ViewReasonDialog
            roomId={roomId}
            onCancel={handleCancel}
            onConfirmed={(data) => {
              setViewResult(data);
              setCursor(nextCursor(data));
            }}
          />
        </DetailLayout>
      </PageContainer>
    );
  }

  // 서버는 `(created_at, id) DESC`로 준다(최신→과거). "더 보기"로 이어 받는 다음
  // 페이지는 항상 그 이전 페이지의 커서보다 더 과거이므로, 도착 순서대로 이어 붙이기만 해도
  // `[...viewResult.items, ...olderItems]`는 그 자체로 전체가 최신→과거 정렬이다(페이지 경계에서
  // 별도 정렬/병합이 필요 없다). 화면은 "위가 과거, 아래가 최신"으로 보여준다(대화를 실제로 나눈
  // 순서 그대로 위→아래로 읽히는 게 관리자에게도 익숙한 채팅 UI 관습이라 그대로 따름) — 그래서
  // 렌더 직전에 한 번만 뒤집는다. "더 보기"는 과거를 불러오므로 목록 위쪽에 둔다.
  const displayItems = [...viewResult.items, ...olderItems].reverse();

  return (
    <PageContainer>
      <ChatMessagesHeader userId={userId} />

      <DetailLayout actions={null}>
        <RoomMemorySection note={viewResult.memoryNote} summary={viewResult.memorySummary} />

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
                  aria-disabled={messagesPager.isFetching}
                  onClick={() => {
                    if (!messagesPager.isFetching) void handleLoadMore();
                  }}
                  className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
                >
                  {messagesPager.isFetching ? "불러오는 중..." : "더 보기"}
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
      </DetailLayout>
    </PageContainer>
  );
}

function ChatMessagesHeader({ userId }: { userId: string }) {
  return (
    <PageHeader
      title="채팅 열람"
      back={
        <Button asChild variant="ghost" size="sm" className="self-start">
          <Link to="/users/$userId" params={{ userId }}>
            <ChevronLeft aria-hidden />
            유저 상세로
          </Link>
        </Button>
      }
    />
  );
}

function nextCursor(page: AdminChatMessagesResponse): ChatMessagesCursor | undefined {
  return page.beforeCreatedAt && page.beforeId
    ? { beforeCreatedAt: page.beforeCreatedAt, beforeId: page.beforeId }
    : undefined;
}

function ChatMessageRow({ item }: { item: AdminChatMessageItem }) {
  const isUser = item.role === "user";
  return (
    <li className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}>
      <span className="text-xs font-medium text-muted-foreground">
        {ROLE_LABELS[item.role]} · {formatDateTime(item.createdAt)}
      </span>
      {/* 관리자가 남의 대화를 읽는 화면이라 web(MessageBubble)의 `primary` 말풍선을 그대로 옮기지
       * 않는다 — `primary`는 "지금 누를 수 있는 것"과 "지금 내가 한 말"에만 쓰는데, 여기서 admin은
       * 어느 쪽 화자도 아니다. 정렬(사용자 오른쪽/AI 왼쪽)은 두 화면 사용자에게 익숙한 채팅 관습을
       * 그대로 따르되, 색은 둘 다 무채색으로 두고 배경 톤 차이(`secondary` vs `card`+border)로만
       * 구분한다. */}
      <p
        className={cn(
          "max-w-3/4 whitespace-pre-wrap break-keep rounded-lg px-3.5 py-2.5 text-sm text-foreground wrap-anywhere",
          isUser ? "bg-secondary" : "border border-border bg-card",
        )}
      >
        {item.content}
      </p>
    </li>
  );
}

/** 방 기억 — 사용자 노트("꼭 기억할 것")와 현재 요약("지금까지의 이야기"). 노트는 매 턴 모델에 그대로
 * 실리는 사용자 입력이라 악용 조사의 대상이고, 이 열람(사유·감사 로그)이 그것을 보는 유일한 경로다. */
function RoomMemorySection({
  note,
  summary,
}: {
  note: string;
  summary?: NonNullable<AdminChatRoomView["memorySummary"]>;
}) {
  // 사용자가 요약을 빈 칸으로 저장할 수 있다 — 요약이 아직 없는 것과 문장을 가른다.
  const emptySummaryText = summary ? "비어 있어요." : "아직 요약이 없어요.";
  return (
    <section aria-labelledby="room-memory-heading" className="flex flex-col gap-3 rounded-xl border border-border p-4">
      <h2 id="room-memory-heading" className="text-lg font-semibold text-foreground">
        기억 노트
      </h2>
      <div className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground">꼭 기억할 것</h3>
        {note ? (
          <p className="whitespace-pre-wrap break-keep text-sm text-foreground wrap-anywhere">{note}</p>
        ) : (
          <p className="text-sm text-muted-foreground">비어 있어요.</p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground">
          지금까지의 이야기{summary && ` · ${SUMMARY_SOURCE_LABELS[summary.source]}`}
        </h3>
        {summary?.text ? (
          <p className="whitespace-pre-wrap break-keep text-sm text-foreground wrap-anywhere">{summary.text}</p>
        ) : (
          <p className="text-sm text-muted-foreground">{emptySummaryText}</p>
        )}
      </div>
    </section>
  );
}
