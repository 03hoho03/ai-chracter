import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS, CONTENT_VISIBILITY_LABELS, MODERATION_STATUS_LABELS, useContentDetailQuery } from "@/entities/admin-content";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { ContentActionPanel } from "./ContentActionPanel";

type ContentDetailPageProps = {
  contentId: string;
};

export function ContentDetailPage({ contentId }: ContentDetailPageProps) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/contents">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">작품 상세</h1>

      <ContentDetailBody contentId={contentId} />
    </main>
  );
}

type ContentDetailBodyProps = {
  contentId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ContentDetailBody({ contentId }: ContentDetailBodyProps) {
  const contentDetailQuery = useContentDetailQuery(contentId);

  if (contentDetailQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (contentDetailQuery.isError) {
    return <p className="text-sm text-destructive-text">작품 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  return (
    <>
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
        <div className="flex gap-4">
          <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted">
            {contentDetailQuery.data.thumbnailUrl && (
              <img src={contentDetailQuery.data.thumbnailUrl} alt="" className="size-full object-cover" />
            )}
          </div>
          <div className="flex min-w-0 flex-col justify-center gap-1">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <span>{CONTENT_TYPE_LABELS[contentDetailQuery.data.type]}</span>
              <span aria-hidden>·</span>
              <span>{CONTENT_VISIBILITY_LABELS[contentDetailQuery.data.visibility]}</span>
              <span aria-hidden>·</span>
              <span>{MODERATION_STATUS_LABELS[contentDetailQuery.data.moderationStatus]}</span>
            </div>
            <p className="truncate text-base font-semibold text-foreground">
              {contentDetailQuery.data.name || "(이름 없음)"}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatDateTime(contentDetailQuery.data.createdAt)} 등록
            </p>
          </div>
        </div>

        <dl className="grid grid-cols-3 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">조회수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(contentDetailQuery.data.viewCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">좋아요수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(contentDetailQuery.data.likeCount)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">채팅수</dt>
            <dd className="tabular-nums text-foreground">{formatCount(contentDetailQuery.data.chatCount)}</dd>
          </div>
        </dl>

        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium text-foreground">설명</h3>
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">
            {contentDetailQuery.data.detailDescription || "-"}
          </p>
        </div>

        {contentDetailQuery.data.prompt && (
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-medium text-foreground">프롬프트 원문</h3>
            <p className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm text-muted-foreground">
              {contentDetailQuery.data.prompt}
            </p>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">제작자</h2>
        {/* 유저 상세 화면은 3단계에서 생긴다 — 그때 이메일/닉네임에 링크를 건다. */}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">이메일</dt>
            <dd className="text-foreground">{contentDetailQuery.data.creator.email}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">닉네임</dt>
            <dd className="text-foreground">{contentDetailQuery.data.creator.nickname}</dd>
          </div>
        </dl>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">버전 이력</h2>
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>버전</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>발행일시</TableHead>
                <TableHead>생성일시</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contentDetailQuery.data.versions.map((version) => (
                <TableRow key={version.id}>
                  <TableCell>{version.name || "(이름 없음)"}</TableCell>
                  <TableCell>{version.versionNumber ?? "-"}</TableCell>
                  <TableCell className="text-muted-foreground">{version.isDraft ? "초안" : "발행됨"}</TableCell>
                  <TableCell>
                    {formatDateTime(version.publishedAt)}
                  </TableCell>
                  <TableCell>{formatDateTime(version.createdAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <ContentActionPanel
        contentId={contentDetailQuery.data.id}
        contentName={contentDetailQuery.data.name || "(이름 없음)"}
        moderationStatus={contentDetailQuery.data.moderationStatus}
      />
    </>
  );
}
