import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useState } from "react";

import { isPromptLane, PROMPT_LANE_LABELS, PROMPT_LANES, type PromptLane } from "../model/lane";
import { PromptLaneEditor } from "./PromptLaneEditor";
import { VersionHistorySection } from "./VersionHistorySection";

/** prompt-scope-techspec.md TS-A — 레인 축은 페이지 안 상위 탭이다. `TabsContent`에
 * `forceMount` + `data-[state=inactive]:hidden`을 함께 써서(관용구 선례
 * `apps/web/src/widgets/image-studio/ui/ImageStudioShell.tsx:180`) 세 레인이 항상
 * 마운트된 채로 숨어 있게 한다 — 레인을 바꿔도 각 레인의 `useForm` 인스턴스(미저장 편집)가
 * 사라지지 않는다. */
export function PromptSetsPage() {
  const [activeLane, setActiveLane] = useState<PromptLane>(() => PROMPT_LANES[0] ?? "story");

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">프롬프트 세트 관리</h1>

      <Tabs
        value={activeLane}
        onValueChange={(value) => {
          if (isPromptLane(value)) setActiveLane(value);
        }}
      >
        <div className="overflow-x-auto">
          <TabsList variant="line">
            {PROMPT_LANES.map((lane) => (
              <TabsTrigger key={lane} value={lane}>
                {PROMPT_LANE_LABELS[lane]}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        {PROMPT_LANES.map((lane) => (
          <TabsContent key={lane} value={lane} forceMount className="pt-4 data-[state=inactive]:hidden">
            <PromptLaneEditor lane={lane} />
          </TabsContent>
        ))}
      </Tabs>

      <VersionHistorySection />
    </main>
  );
}
