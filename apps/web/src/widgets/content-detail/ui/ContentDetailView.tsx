import { useSetAtom } from "jotai";
import { BookOpen, ImageOff, UserRound } from "lucide-react";
import { Link } from "@tanstack/react-router";

import {
  canViewDetailPage,
  toContentAccessStatus,
  useContentDetailQuery,
  type ContentType,
} from "../../../entities/content";
import { contentDetailModalAtom } from "../../../shared/model/content-detail-modal";
import { ContentUnavailableState } from "./ContentUnavailableState";

const TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

function ContentDetailSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-1">
      <div className="aspect-video w-full animate-pulse rounded-lg bg-muted" />
      <div className="h-6 w-2/3 animate-pulse rounded bg-muted" />
      <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
      <div className="h-20 w-full animate-pulse rounded bg-muted" />
    </div>
  );
}

/** techspec-content-detail.md §1~2 — 모달/풀페이지 공용 상세 콘텐츠. 카드가 있는 모든 리스트
 * (홈, 프로필)는 이 컴포넌트를 직접 렌더링하지 않고 `useContentDetailModal().open()`만 호출한다. */
export function ContentDetailView({ id }: { id: string }) {
  const detailQuery = useContentDetailQuery(id);
  const setModalState = useSetAtom(contentDetailModalAtom);

  if (detailQuery.isPending) return <ContentDetailSkeleton />;

  if (detailQuery.isError) {
    return (
      <p className="p-6 text-center text-sm text-destructive">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const content = detailQuery.data;
  const access = toContentAccessStatus(content.accessStatus);

  if (!canViewDetailPage(access, content.isOwner)) {
    return <ContentUnavailableState access={access} />;
  }

  return (
    <article className="flex flex-col gap-5 p-1">
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-muted">
        {content.thumbnailUrl ? (
          <img src={content.thumbnailUrl} alt="" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className="inline-flex w-fit items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
          {content.type === "character" ? (
            <UserRound aria-hidden className="size-3.5" />
          ) : (
            <BookOpen aria-hidden className="size-3.5" />
          )}
          {TYPE_LABEL[content.type]}
        </span>

        <h1 className="text-xl font-bold tracking-tight text-foreground">{content.name}</h1>

        <Link
          to="/profile/$userId"
          params={{ userId: content.creatorUserId }}
          onClick={() => setModalState(null)}
          className="w-fit text-sm text-muted-foreground hover:underline"
        >
          {content.creatorNickname}
        </Link>

        <p className="text-xs text-muted-foreground">{content.genreName}</p>

        {content.hashtags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {content.hashtags.map((tag) => (
              <span key={tag} className="text-xs text-muted-foreground">
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>

      <p className="text-sm font-medium text-foreground">{content.oneLiner}</p>

      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{content.detailDescription}</p>
    </article>
  );
}
