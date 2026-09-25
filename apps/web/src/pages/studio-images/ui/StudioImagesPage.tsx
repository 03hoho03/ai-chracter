import { ImageStudioShell, type ImageStudioTab } from "@/widgets/image-studio";

export function StudioImagesPage({
  tab,
  onTabChange,
}: {
  tab: ImageStudioTab;
  onTabChange: (tab: ImageStudioTab) => void;
}) {
  return (
    // <main>은 이 페이지가 소유한다 — 제목·설명과 3열 셸을 둘 다 감싸야 lg 미만에서 스크린리더가
    // 랜드마크로 건너뛰어도 제목을 지나치지 않는다(랜드마크는 감싸기만, 폭·높이 제약은 ImageStudioShell
    // 안쪽 행에 그대로 있다 — DESIGN.md §Layout containers, 대화방 선례).
    <main>
      {/* `lg` 이상에서 없애던 제목 블록을 확장: lg 미만에서도 감춘다(2026-09-14 사용자 피드백).
          h1 은 문서 개요를 위해 sr-only 로 남긴다. */}
      <h1 className="sr-only">이미지</h1>
      <ImageStudioShell tab={tab} onTabChange={onTabChange} />
    </main>
  );
}
