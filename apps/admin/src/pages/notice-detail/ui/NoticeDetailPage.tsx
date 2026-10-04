import { Button } from "@ai-character-chat/ui/components/button";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { useNoticeDetailQuery } from "@/entities/notice";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { NoticeEditor } from "./NoticeEditor";

type NoticeDetailPageProps = {
  /** `"new"`이면 아직 생성되지 않은 새 공지다(`/notices/new`, sentinel). */
  noticeId: string;
};

export function NoticeDetailPage({ noticeId }: NoticeDetailPageProps) {
  // 마지막으로 본 목록(필터·검색어·페이지)으로 돌아간다 — 대시보드 등 다른 입구로 들어왔어도 같다.
  const rememberedListSearch = useRememberedListSearch("/notices/");
  const isNew = noticeId === "new";

  return (
    <PageContainer>
      <PageHeader
        title={isNew ? "새 공지" : "공지 편집"}
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/notices" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      {/* 편집 폼이 본문이라 조치 열·하단 바가 없다. 본문 열 폭만 상세와 같게 받는다. */}
      <DetailLayout actions={null}>{isNew ? <NewNotice /> : <ExistingNotice noticeId={noticeId} />}</DetailLayout>
    </PageContainer>
  );
}

function NewNotice() {
  useDocumentTitle("새 공지");
  const navigate = useNavigate();

  return (
    <NoticeEditor
      notice={null}
      // 저장 직후 같은 처리 안에서 옮겨 가 화면이 아직 "변경 있음"으로 그려져 있다 — 이미 저장했으니 이탈 확인을 건너뛴다.
      onCreated={(id) =>
        void navigate({ to: "/notices/$noticeId", params: { noticeId: id }, replace: true, ignoreBlocker: true })
      }
    />
  );
}

type ExistingNoticeProps = {
  noticeId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportDetailPage` 관용구). */
function ExistingNotice({ noticeId }: ExistingNoticeProps) {
  const noticeDetailQuery = useNoticeDetailQuery(noticeId);
  useDocumentTitle("공지 편집", noticeDetailQuery.data?.title);

  // `key`로 공지 사이 이동 시 편집 버퍼(`NoticeEditor`의 RHF `defaultValues`)를 강제로 초기화한다 —
  // 같은 라우트(`/notices/$noticeId`)라 id만 바뀌면 컴포넌트가 재마운트되지 않고,
  // `defaultValues`는 마운트 시점 값이라 스스로는 새 공지를 따라가지 않는다.
  return (
    <QueryState query={noticeDetailQuery} errorMessage="공지를 불러오지 못했어요.">
      {(notice) => <NoticeEditor key={notice.id} notice={notice} />}
    </QueryState>
  );
}
