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
      {/* image-refact-goal-prompt.md IR-17 — lg 이상은 탭 스트립이 제목 역할을 대신하고(크랙과
          동일), h-below-header 3열 셸에서 세로 공간을 아낀다. lg 미만은 유지한다 — 폰 헤더에는
          페이지 이름이 없다. */}
      <div className="mx-auto flex max-w-2xl flex-col gap-1.5 px-4 pt-10 sm:px-6 lg:hidden">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이미지</h1>
        <p className="text-sm text-muted-foreground">
          프롬프트와 스타일로 이미지를 생성하고, 만든 이미지를 모아 봐요.
        </p>
      </div>
      <ImageStudioShell tab={tab} onTabChange={onTabChange} />
    </main>
  );
}
