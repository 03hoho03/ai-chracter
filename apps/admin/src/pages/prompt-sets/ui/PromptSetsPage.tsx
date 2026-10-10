import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useCallback, useState } from "react";

import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { PageContainer } from "@/shared/ui/PageContainer";
import { UnsavedChangesGuard } from "@/shared/ui/UnsavedChangesGuard";

import { isPromptLane, PROMPT_LANE_LABELS, PROMPT_LANES, type PromptLane } from "../model/lane";
import {
  isPromptModel,
  PROMPT_MODEL_LABELS,
  promptChainKey,
  promptModelsFor,
  type PromptChainKey,
  type PromptModel,
} from "../model/model";
import { PromptLaneEditor } from "./PromptLaneEditor";
import { VersionHistorySection } from "./VersionHistorySection";

const INITIAL_MODEL_BY_LANE: Record<PromptLane, PromptModel> = {
  story: "gemini",
  character: "gemini",
  publish_filter: "gemini",
  novel: "gemini",
  novel_screen: "gemini",
};

/** 레인 축은 페이지 안 상위 탭이고, 스토리·캐릭터·소설 레인 안에 모델 하위 탭(Gemini·Claude Sonnet·Claude Opus, 스토리·캐릭터는
 * 판정 전용 하나 더)이 있다 — (레인, 모델)마다 초안·게시가 따로인 독립 체인이다(발행 심사·노벨 심사는 Gemini 하나뿐이라 하위 탭이
 * 없다).
 *
 * 편집기는 한 번 열린 뒤에는 `forceMount` + `data-[state=inactive]:hidden`으로(같은 관용구가 web
 * `ImageStudioShell.tsx`의 생성 `TabsContent`에도 있다) 마운트된 채로 숨는다 — 탭을 바꿔도 그 체인의 `useForm`
 * 인스턴스(미저장 편집)가 사라지지 않게. 다만 **처음 마운트는 체인마다 다르다**: 레인마다 Gemini 체인은 페이지와 함께
 * 마운트하고, 나머지 체인(Claude·판정 전용)은 그 하위 탭을 처음 열 때 마운트한다. 모든 체인을 미리 올리면 첫 로드에 늦게 올리는
 * 체인마다 초안·미리보기 요청이 하나씩 늘고 그 섹션 편집칸이 모두 숨은 채 생기는데, 상위 모델이 꺼져 있는 동안 Claude 세트는 거의 열지 않는다.
 * 열지 않은 체인에는 미저장 편집이 있을 수 없으니 늦게 올려도 보존할 것을 잃지 않는다.
 *
 * 다른 화면으로 떠나면 편집이 사라지므로, 체인마다 알려 오는 "변경 있음"을 모아 하나라도 있으면 확인을 받는다(확인 창이
 * 체인 수만큼 뜨지 않게 가드는 여기 하나다). */
export function PromptSetsPage() {
  useDocumentTitle("프롬프트 관리");
  const [activeLane, setActiveLane] = useState<PromptLane>(() => PROMPT_LANES[0] ?? "story");
  const [activeModelByLane, setActiveModelByLane] = useState(INITIAL_MODEL_BY_LANE);
  const [mountedChains, setMountedChains] = useState<ReadonlySet<PromptChainKey>>(
    () => new Set(PROMPT_LANES.map((lane) => promptChainKey(lane, "gemini"))),
  );
  const [dirtyByChain, setDirtyByChain] = useState<Partial<Record<PromptChainKey, boolean>>>({});
  const hasUnsavedChain = Object.values(dirtyByChain).some((isDirty) => isDirty === true);
  // 체인 폼이 효과에서 부르므로 참조가 늘 같아야 하고, 값이 같으면 상태를 바꾸지 않는다 — 아니면 알림 → 다시 그림 →
  // 새 함수 → 다시 알림이 끝없이 돈다.
  const handleDirtyChange = useCallback((chain: PromptChainKey, isDirty: boolean) => {
    setDirtyByChain((prev) => (prev[chain] === isDirty ? prev : { ...prev, [chain]: isDirty }));
  }, []);

  const selectModel = (lane: PromptLane, model: PromptModel) => {
    setActiveModelByLane((prev) => ({ ...prev, [lane]: model }));
    const chain = promptChainKey(lane, model);
    setMountedChains((prev) => (prev.has(chain) ? prev : new Set(prev).add(chain)));
  };

  return (
    <PageContainer>
      <h1 className="text-2xl font-bold tracking-tight text-foreground">프롬프트 관리</h1>

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
          // Radix 탭 패널은 Tab 정지(`tabIndex=0`)인데 이 패널은 안의 편집칸·버튼이 진입점이다 — 정지를 빼야 포커스가
          // 보이지 않는 패널에 한 번 앉지 않는다.
          <TabsContent
            key={lane}
            value={lane}
            forceMount
            tabIndex={-1}
            className="pt-4 data-[state=inactive]:hidden"
          >
            <LaneModelTabs
              lane={lane}
              activeModel={activeModelByLane[lane]}
              mountedChains={mountedChains}
              onSelectModel={selectModel}
              onDirtyChange={handleDirtyChange}
            />
          </TabsContent>
        ))}
      </Tabs>

      <VersionHistorySection />

      <UnsavedChangesGuard isDirty={hasUnsavedChain} />
    </PageContainer>
  );
}

type LaneModelTabsProps = {
  lane: PromptLane;
  activeModel: PromptModel;
  mountedChains: ReadonlySet<PromptChainKey>;
  onSelectModel: (lane: PromptLane, model: PromptModel) => void;
  onDirtyChange: (chain: PromptChainKey, isDirty: boolean) => void;
};

/** 모델이 하나뿐인 레인(발행 심사)은 하위 탭 없이 편집기만 그린다. */
function LaneModelTabs({ lane, activeModel, mountedChains, onSelectModel, onDirtyChange }: LaneModelTabsProps) {
  const models = promptModelsFor(lane);

  if (models.length === 1) {
    return <PromptLaneEditor lane={lane} model="gemini" onDirtyChange={onDirtyChange} />;
  }

  return (
    <Tabs
      value={activeModel}
      onValueChange={(value) => {
        if (isPromptModel(value)) onSelectModel(lane, value);
      }}
      className="gap-4"
    >
      {/* 레인·채널 탭(밑줄)과 층이 다른 축이라 모양을 달리해 세그먼트로 둔다. 활성 칸의 기본 그림자는 정지 상태 그림자라
       * 끄고, 대신 테두리로 고른 칸을 가른다. 좁은 화면에서는 이 줄만 가로로 스크롤한다. */}
      <div className="overflow-x-auto">
        <TabsList aria-label={`${PROMPT_LANE_LABELS[lane]} 레인 모델`}>
          {models.map((model) => (
            <TabsTrigger
              key={model}
              value={model}
              className="px-3 group-data-[variant=default]/tabs-list:data-active:shadow-none data-active:border-border"
            >
              {PROMPT_MODEL_LABELS[model]}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      {models.map((model) =>
        mountedChains.has(promptChainKey(lane, model)) ? (
          // 바깥 레인 패널과 같은 이유로 Tab 정지를 뺀다.
          <TabsContent
            key={model}
            value={model}
            forceMount
            tabIndex={-1}
            className="data-[state=inactive]:hidden"
          >
            <PromptLaneEditor lane={lane} model={model} onDirtyChange={onDirtyChange} />
          </TabsContent>
        ) : null,
      )}
    </Tabs>
  );
}
