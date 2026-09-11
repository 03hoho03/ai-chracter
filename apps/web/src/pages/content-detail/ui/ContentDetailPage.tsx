import { ContentDetailView } from "@/widgets/content-detail";

/** techspec-content-detail.md §1 — 상세화면 고유 URL로 직접 진입했을 때만 매치되는 풀페이지 레이아웃.
 * design-system-progress.md P-5(D-7) — `lg` 미만에서 플레이 CTA가 `fixed`로 바닥에 붙으므로, 그
 * 높이(p-4 16px×2 + 버튼 48px ≈ 80px + safe-area)만큼 하단 여백을 더 줘 마지막 콘텐츠가 가려지지
 * 않게 한다. `lg`부터는 CTA가 다시 본문 안 인라인으로 돌아가므로 원래 여백(`py-10`)으로 되돌린다. */
export function ContentDetailPage({ id }: { id: string }) {
  return (
    <main className="mx-auto max-w-2xl px-4 sm:px-6 py-10 pb-[calc(6rem+env(safe-area-inset-bottom))] lg:pb-10">
      <ContentDetailView id={id} variant="page" />
    </main>
  );
}
