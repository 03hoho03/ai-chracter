import type { ContentType } from "@/entities/content";
import { ContentDetailView } from "@/widgets/content-detail";
import { ContentComments } from "@/widgets/content-comments";

type ContentDetailPageProps = { id: string; type: ContentType; targetCommentId?: string };

/** 상세화면 고유 URL로 직접 진입했을 때만 매치되는 풀페이지 레이아웃.
 * `lg` 미만에서 플레이 CTA가 `fixed`로 바닥에 붙지만, 마지막 콘텐츠를 그 바 위로 올리는 하단 여백은 여기서
 * 지지 않는다 — 이 라우트에서 문서의 마지막 요소는 언제나 사이트 푸터이고, 그 푸터가 바 높이만큼의 여백을 진다. */
export function ContentDetailPage({ id, type, targetCommentId }: ContentDetailPageProps) {
  return (
    <main data-content-detail className="mx-auto max-w-2xl px-4 sm:px-6 py-10">
      <ContentDetailView id={id} type={type} variant="page"
        comments={<ContentComments key={id} contentId={id} targetCommentId={targetCommentId} />} />
    </main>
  );
}
