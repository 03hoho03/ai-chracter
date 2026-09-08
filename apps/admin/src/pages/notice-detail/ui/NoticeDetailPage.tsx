import { Button } from "@ai-character-chat/ui/components/button";
import { Link, useNavigate } from "@tanstack/react-router";

import { useNoticeDetailQuery } from "@/entities/notice";

import { NoticeEditor } from "./NoticeEditor";

type NoticeDetailPageProps = {
  /** `"new"`이면 아직 생성되지 않은 새 공지다(`/notices/new`, sentinel). */
  noticeId: string;
};

export function NoticeDetailPage({ noticeId }: NoticeDetailPageProps) {
  const isNew = noticeId === "new";

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/notices">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">{isNew ? "새 공지" : "공지 편집"}</h1>

      {isNew ? <NewNotice /> : <ExistingNotice noticeId={noticeId} />}
    </main>
  );
}

function NewNotice() {
  const navigate = useNavigate();

  return (
    <NoticeEditor
      notice={null}
      onCreated={(id) => void navigate({ to: "/notices/$noticeId", params: { noticeId: id }, replace: true })}
    />
  );
}

type ExistingNoticeProps = {
  noticeId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportDetailPage` 관용구). */
function ExistingNotice({ noticeId }: ExistingNoticeProps) {
  const noticeDetailQuery = useNoticeDetailQuery(noticeId);

  if (noticeDetailQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (noticeDetailQuery.isError) {
    return <p className="text-sm text-destructive-text">공지를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  // `key`로 공지 사이 이동 시 편집 버퍼(`NoticeEditor`의 RHF `defaultValues`)를 강제로 초기화한다 —
  // 같은 라우트(`/notices/$noticeId`)라 id만 바뀌면 컴포넌트가 재마운트되지 않고,
  // `defaultValues`는 마운트 시점 값이라 스스로는 새 공지를 따라가지 않는다.
  return <NoticeEditor key={noticeDetailQuery.data.id} notice={noticeDetailQuery.data} />;
}
