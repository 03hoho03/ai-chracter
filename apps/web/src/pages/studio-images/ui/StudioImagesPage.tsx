import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";

import { GenerateImagesPanel } from "@/features/generate-images";

import { GeneratedImageLibraryPanel } from "./GeneratedImageLibraryPanel";

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

      <Tabs
        value={tab}
        onValueChange={(value) => {
          if (value === "generate" || value === "library") onTabChange(value);
        }}
      >
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
          <GeneratedImageLibraryPanel onNavigateToGenerate={() => onTabChange("generate")} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
