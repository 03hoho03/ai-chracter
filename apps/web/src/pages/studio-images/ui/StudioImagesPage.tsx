import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";

import { GenerateImagesPanel } from "@/features/generate-images";

export type StudioImagesTab = "generate" | "library";

export function StudioImagesPage({
  tab,
  onTabChange,
}: {
  tab: StudioImagesTab;
  onTabChange: (tab: StudioImagesTab) => void;
}) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이미지</h1>
        <p className="text-sm text-muted-foreground">
          프롬프트와 스타일로 이미지를 생성하고, 만든 이미지를 모아 봐요.
        </p>
      </div>

      <Tabs value={tab} onValueChange={(value) => onTabChange(value as StudioImagesTab)}>
        <TabsList variant="line">
          <TabsTrigger value="generate">생성</TabsTrigger>
          <TabsTrigger value="library">내 이미지</TabsTrigger>
        </TabsList>

        {/* forceMount — 탭을 오가도 입력 중인 프롬프트와 진행 중인 생성 잡 표시(로컬 state)가
            사라지지 않게 언마운트 대신 숨긴다. */}
        <TabsContent value="generate" forceMount className="data-[state=inactive]:hidden">
          <GenerateImagesPanel />
        </TabsContent>
        <TabsContent value="library">
          {/* prd-image-library US-004가 실제 그리드로 채운다. */}
          <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-border px-6 py-10">
            <p className="text-sm text-muted-foreground">
              생성한 이미지를 모아 보는 화면을 준비하고 있어요.
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </main>
  );
}
