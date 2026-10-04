import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useCallback, useState } from "react";

import { PageContainer } from "@/shared/ui/PageContainer";
import { UnsavedChangesGuard } from "@/shared/ui/UnsavedChangesGuard";

import { isPromptLane, PROMPT_LANE_LABELS, PROMPT_LANES, type PromptLane } from "../model/lane";
import { PromptLaneEditor } from "./PromptLaneEditor";
import { VersionHistorySection } from "./VersionHistorySection";

/** 레인 축은 페이지 안 상위 탭이다. `TabsContent`에
 * `forceMount` + `data-[state=inactive]:hidden`을 함께 써서(같은 관용구가 web
 * `ImageStudioShell.tsx`의 생성 `TabsContent`에도 있다) 세 레인이 항상
 * 마운트된 채로 숨어 있게 한다 — 레인을 바꿔도 각 레인의 `useForm` 인스턴스(미저장 편집)가
 * 사라지지 않는다. 다른 화면으로 떠나면 그 편집이 사라지므로, 레인마다 알려 오는 "변경 있음"을 모아 하나라도 있으면
 * 확인을 받는다(확인 창이 레인 수만큼 뜨지 않게 가드는 여기 하나다). */
export function PromptSetsPage() {
  const [activeLane, setActiveLane] = useState<PromptLane>(() => PROMPT_LANES[0] ?? "story");
  const [dirtyByLane, setDirtyByLane] = useState<Partial<Record<PromptLane, boolean>>>({});
  const hasUnsavedLane = PROMPT_LANES.some((lane) => dirtyByLane[lane] === true);
  // 레인 폼이 효과에서 부르므로 참조가 늘 같아야 하고, 값이 같으면 상태를 바꾸지 않는다 — 아니면 알림 → 다시 그림 →
  // 새 함수 → 다시 알림이 끝없이 돈다.
  const handleDirtyChange = useCallback((lane: PromptLane, isDirty: boolean) => {
    setDirtyByLane((prev) => (prev[lane] === isDirty ? prev : { ...prev, [lane]: isDirty }));
  }, []);

  return (
    <PageContainer>
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
            <PromptLaneEditor lane={lane} onDirtyChange={handleDirtyChange} />
          </TabsContent>
        ))}
      </Tabs>

      <VersionHistorySection />

      <UnsavedChangesGuard isDirty={hasUnsavedLane} />
    </PageContainer>
  );
}
