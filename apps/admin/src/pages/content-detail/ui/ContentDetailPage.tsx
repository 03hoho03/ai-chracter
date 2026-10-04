import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { useId } from "react";

import {
  CONTENT_TYPE_LABELS,
  CONTENT_VISIBILITY_LABELS,
  MODERATION_STATUS_LABELS,
  useContentDetailQuery,
  type AdminContentDetailResponse,
  type ContentModerationStatusFilter,
} from "@/entities/admin-content";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { ContentActionPanel } from "./ContentActionPanel";
import { HomeCurationActions, HomeCurationSection } from "./HomeCurationSection";
import { PublishedImagesSection } from "./PublishedImagesSection";

type ContentDetailPageProps = {
  contentId: string;
};

export function ContentDetailPage({ contentId }: ContentDetailPageProps) {
  // 마지막으로 본 목록(필터·검색어·페이지)으로 돌아간다 — 대시보드 등 다른 입구로 들어왔어도 같다.
  const rememberedListSearch = useRememberedListSearch("/contents/");
  return (
    <PageContainer>
      <PageHeader
        title="작품 상세"
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/contents" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      <ContentDetailBody contentId={contentId} />
    </PageContainer>
  );
}

type ContentDetailBodyProps = {
  contentId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ContentDetailBody({ contentId }: ContentDetailBodyProps) {
  const contentDetailQuery = useContentDetailQuery(contentId);
  useDocumentTitle("작품 상세", contentDetailQuery.data?.name);

  return (
    <QueryState query={contentDetailQuery} skeleton="detail" errorMessage="작품 정보를 불러오지 못했어요.">
      {(content) => {
        const contentName = content.name || "(이름 없음)";
        const { moderationStatus } = content;
        const isDeleted = moderationStatus === "deleted";

        return (
          <DetailLayout
            actions={
              // 삭제된 작품은 걸 수 있는 조치가 없다. 삭제 전에 지정된 홈 큐레이션의 해제만 본문 카드에 남긴다.
              moderationStatus === "deleted"
                ? null
                : {
                    title: "조치",
                    triggerLabel: "조치하기",
                    summary: `${CONTENT_VISIBILITY_LABELS[content.visibility]} · ${MODERATION_STATUS_LABELS[moderationStatus]}`,
                    render: (host) => (
                      <ContentActions
                        content={content}
                        contentName={contentName}
                        moderationStatus={moderationStatus}
                        onSuccess={host.onDone}
                      />
                    ),
                  }
            }
          >
            <ContentSummary content={content} contentName={contentName} />

            <PublishedImagesSection images={content.publishedImages} />

            <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
              <h2 className="text-lg font-semibold text-foreground">제작자</h2>
              {/* 할 일: 이메일/닉네임에 유저 상세 화면 링크를 건다. */}
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <div className="min-w-0">
                  <dt className="text-muted-foreground">이메일</dt>
                  <dd className="text-foreground wrap-anywhere">{content.creator.email}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-muted-foreground">닉네임</dt>
                  <dd className="break-keep text-foreground wrap-anywhere">{content.creator.nickname}</dd>
                </div>
              </dl>
            </section>

            <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
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
                    {content.versions.map((version) => (
                      <TableRow key={version.id}>
                        {/* 작가가 쓴 이름이라 길 수 있다 — 이 칸만 줄바꿈해 날짜 칸이 표 밖으로 밀리지 않게 한다. */}
                        <TableCell className="min-w-32 whitespace-normal break-keep wrap-anywhere">
                          {version.name || "(이름 없음)"}
                        </TableCell>
                        <TableCell>{version.versionNumber ?? "-"}</TableCell>
                        <TableCell className="text-muted-foreground">{version.isDraft ? "초안" : "발행됨"}</TableCell>
                        <TableCell>{formatDateTime(version.publishedAt)}</TableCell>
                        <TableCell>{formatDateTime(version.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </section>

            {isDeleted && (
              <HomeCurationSection
                contentId={content.id}
                contentType={content.type}
                contentName={contentName}
                moderationStatus={moderationStatus}
              />
            )}
          </DetailLayout>
        );
      }}
    </QueryState>
  );
}

type ContentSummaryProps = {
  content: AdminContentDetailResponse;
  contentName: string;
};

function ContentSummary({ content, contentName }: ContentSummaryProps) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6">
      <div className="flex gap-4">
        <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary">
          {!!content.thumbnailUrl && <img src={content.thumbnailUrl} alt="" className="size-full object-cover" />}
        </div>
        <div className="flex min-w-0 flex-col justify-center gap-1">
          <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <span>{CONTENT_TYPE_LABELS[content.type]}</span>
            <span aria-hidden>·</span>
            <span>{CONTENT_VISIBILITY_LABELS[content.visibility]}</span>
            <span aria-hidden>·</span>
            <span>{MODERATION_STATUS_LABELS[content.moderationStatus]}</span>
          </div>
          <p className="break-keep text-lg font-semibold text-foreground wrap-anywhere">{contentName}</p>
          <p className="text-xs text-muted-foreground">{formatDateTime(content.createdAt)} 등록</p>
        </div>
      </div>

      {content.moderationStatus === "deleted" && <p className="text-sm text-muted-foreground">삭제된 작품입니다.</p>}

      <dl className="grid grid-cols-3 gap-x-6 gap-y-2 text-sm">
        <div>
          <dt className="text-muted-foreground">조회수</dt>
          <dd className="tabular-nums text-foreground">{formatCount(content.viewCount)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">좋아요수</dt>
          <dd className="tabular-nums text-foreground">{formatCount(content.likeCount)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">채팅수</dt>
          <dd className="tabular-nums text-foreground">{formatCount(content.chatCount)}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-foreground">설명</h3>
        <p className="whitespace-pre-wrap break-keep text-sm text-muted-foreground wrap-anywhere">
          {content.detailDescription || "-"}
        </p>
      </div>

      {!!content.prompt && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium text-foreground">프롬프트 원문</h3>
          <p className="whitespace-pre-wrap rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
            {content.prompt}
          </p>
        </div>
      )}
    </section>
  );
}

type ContentActionsProps = {
  content: AdminContentDetailResponse;
  contentName: string;
  moderationStatus: Exclude<ContentModerationStatusFilter, "deleted">;
  onSuccess: () => void;
};

/** 조치 열·시트 하나에 홈 큐레이션과 상태 조치를 두 묶음으로 둔다 — 둘 다 이 작품을 운영자가 바꾸는 일이라 한 자리에서
 * 찾게 하고, 묶음 제목으로 갈라 어느 쪽 버튼인지 헷갈리지 않게 한다. */
function ContentActions({ content, contentName, moderationStatus, onSuccess }: ContentActionsProps) {
  const curationHeadingId = useId();
  const moderationHeadingId = useId();

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby={curationHeadingId} className="flex flex-col gap-2">
        <h3 id={curationHeadingId} className="text-sm font-semibold text-foreground">
          홈 큐레이션
        </h3>
        <HomeCurationActions
          contentId={content.id}
          contentType={content.type}
          contentName={contentName}
          moderationStatus={moderationStatus}
          onSuccess={onSuccess}
        />
      </section>

      <section aria-labelledby={moderationHeadingId} className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 id={moderationHeadingId} className="text-sm font-semibold text-foreground">
          상태 조치
        </h3>
        <ContentActionPanel
          contentId={content.id}
          contentName={contentName}
          moderationStatus={moderationStatus}
          onSuccess={onSuccess}
        />
      </section>
    </div>
  );
}
