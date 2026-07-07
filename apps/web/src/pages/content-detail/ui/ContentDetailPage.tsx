import { ContentDetailView } from "../../../widgets/content-detail";

/** techspec-content-detail.md §1 — 상세화면 고유 URL로 직접 진입했을 때만 매치되는 풀페이지 레이아웃. */
export function ContentDetailPage({ id }: { id: string }) {
  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <ContentDetailView id={id} />
    </main>
  );
}
