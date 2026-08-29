import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { useContentVersionsQuery } from "@/entities/content";

const VERSION_DATE_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** techspec-content-detail.md §6, US-017 — 조회 전용 버전 이력. 전환 액션은 없다(그건
 * techspec-chat-story.md §6의 UpdateInfoModal이 대화방 화면에서 별도로 담당). */
export function VersionHistoryModal({
  contentId,
  open,
  onOpenChange,
}: {
  contentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const versionsQuery = useContentVersionsQuery(contentId, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>업데이트 정보</DialogTitle>
          <DialogDescription>지금까지의 버전 이력이에요. 여기서 과거 버전으로 전환할 수는 없어요.</DialogDescription>
        </DialogHeader>

        <VersionHistoryBody query={versionsQuery} />
      </DialogContent>
    </Dialog>
  );
}

/** 네 상태(로딩·에러·목록·빈 목록)가 배타적이라 early return으로 순서를 강제한다(COMP-04).
 * 삼항으로 이어 붙이면 상태가 하나 늘 때마다 중첩이 깊어지고, 어느 분기가 언제 도는지가
 * 들여쓰기에 묻힌다. */
function VersionHistoryBody({
  query,
}: {
  query: ReturnType<typeof useContentVersionsQuery>;
}) {
  if (query.isPending) {
    return (
      <ul className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <li key={i} className="h-10 animate-pulse rounded-md bg-muted" />
        ))}
      </ul>
    );
  }

  if (query.isError) {
    return (
      <p className="py-4 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const versions = query.data;
  if (versions === undefined || versions.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">버전 이력이 없어요.</p>;
  }

  return (
    <ul className="flex flex-col">
      {versions.map((version) => (
        <li
          key={version.versionNumber}
          className="flex items-center justify-between border-b border-border py-2.5 text-sm last:border-b-0"
        >
          <span className="font-medium text-foreground">v{version.versionNumber}</span>
          <span className="text-muted-foreground">
            {VERSION_DATE_FORMATTER.format(new Date(version.publishedAt))}
          </span>
        </li>
      ))}
    </ul>
  );
}
