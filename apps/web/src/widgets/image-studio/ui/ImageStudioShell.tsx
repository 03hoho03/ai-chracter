import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useAtom } from "jotai";
import { Images, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { useImageJobStatusQuery } from "@/entities/image-job";
import {
  GenerateImagesFormProvider,
  GenerateImagesPromptField,
  GenerateImagesResultGrid,
  GenerateImagesStyleGrid,
  useGenerateImagesMutation,
  type GenerateImagesFormValues,
} from "@/features/generate-images";
import { isApiError } from "@/shared/api/client";

import { imageStudioLibrarySheetOpenAtom, imageStudioOptionsSheetOpenAtom } from "../model/atoms";
import { isImageStudioTab, type ImageStudioTab } from "../model/imageStudioTab";
import { ImageStudioLibraryRail } from "./ImageStudioLibraryRail";
import { ImageStudioOptionsRail } from "./ImageStudioOptionsRail";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// image-refact-techspec.md IT-6/IT-7 — /studio/images의 3열 셸. widgets/chat-room/ui/ChatRoomView.tsx의
// flex 행을 베낀다: w-full이 없으면 flex 컬럼 자식의 auto 마진 때문에 stretch가 꺼져 폭이
// shrink-to-fit으로 붕괴하고(ChatRoomView.tsx:146 실측), min-h-0은 flex 아이템 기본 min-height:auto를
// 되돌린다 — 없으면 열이 콘텐츠만큼 늘어 페이지 전체가 스크롤된다. max-w는 셸이 아니라 이 행에 건다
// (DESIGN.md §Layout containers, 대화방 선례).
export function ImageStudioShell({
  tab,
  onTabChange,
}: {
  tab: ImageStudioTab;
  onTabChange: (tab: ImageStudioTab) => void;
}) {
  const [isLibraryOpen, setIsLibraryOpen] = useAtom(imageStudioLibrarySheetOpenAtom);
  const [isOptionsOpen, setIsOptionsOpen] = useAtom(imageStudioOptionsSheetOpenAtom);

  // features/generate-images가 조각을 한 열로 쌓아 두던 옛 조합 컴포넌트가 갖고 있던 잡 폴링·
  // 제출 로직 — 3열로 조각을 흩는 이 셸이 그 조합을 대신하면서 쓰는 곳이 없어져 지웠고(고아 정리),
  // 로직만 여기로 옮겼다.
  const [jobId, setJobId] = useState<string | undefined>(undefined);
  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(jobId ?? "", jobId !== undefined);

  async function handleSubmit(values: GenerateImagesFormValues) {
    setJobId(undefined);
    try {
      const response = await generateMutation.mutateAsync(values);
      setJobId(response.jobId);
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      toast.error(apiError?.status === 422 ? "입력값을 다시 확인해주세요." : GENERIC_ERROR_MESSAGE);
    }
  }

  return (
    // 랜드마크 <main>은 StudioImagesPage(페이지)가 소유한다 — 이 위젯은 제목 블록과 형제로
    // 놓이므로 여기서 또 <main>을 열면 페이지에 랜드마크가 두 개 생긴다. 폭·높이 제약은
    // (DESIGN.md §Layout containers, 대화방 선례대로) 셸이 아니라 이 행에 그대로 건다.
    <div className="mx-auto flex w-full min-h-0 max-w-2xl flex-col lg:h-below-header lg:max-w-7xl lg:flex-row">
      {/* 좌열 — lg 이상만 보인다(그림자 없음, 경계는 border-r 한 줄, DESIGN.md Flat-at-Rest). */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
        <ImageStudioLibraryRail />
      </aside>

      {/* image-refact-techspec.md IT-9 — GenerateImagesFormProvider는 중앙(Prompt/Style/Result)과
          우열(Options) 양쪽의 공통 조상이어야 폼 context가 닿는다(React context는 DOM 위치와
          무관). 좌열(보관함)은 그 바깥에 둔다 — 모델을 못 불러와 이 프로바이더가 "이용 불가" 화면으로
          바뀌어도 이미 만든 보관함까지 함께 가려지면 안 된다. */}
      <GenerateImagesFormProvider onSubmit={handleSubmit}>
        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (isImageStudioTab(value)) onTabChange(value);
          }}
          className="flex min-h-0 min-w-0 flex-1 flex-col gap-0"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3 sm:px-6">
            <TabsList variant="line">
              <TabsTrigger value="generate">생성</TabsTrigger>
              {/* image-refact-techspec.md IT-10 — 저장소 최초의 disabled 탭. GenerateImagesStyleGrid의
                  "· 준비 중" 표기(§0-13)와 같은 어법을 접근 가능한 이름에도 남긴다. */}
              <TabsTrigger value="transform" disabled>
                변형 · 준비 중
              </TabsTrigger>
              <TabsTrigger value="inpaint" disabled>
                인페인트 · 준비 중
              </TabsTrigger>
            </TabsList>

            {/* image-refact-goal-prompt.md IR-6a — 시트 트리거 2개. 크랙은 size-12(48px)지만 우리
                사다리엔 48px이 없다(DESIGN.md:245) — 헤더 선례(Header.tsx:40)와 같은 size="icon".
                크랙과 달리 aria-label을 단다(크랙엔 접근 가능한 이름이 없다, 실측). */}
            <div className="flex items-center gap-1 lg:hidden">
              <Button
                variant="ghost"
                size="icon"
                aria-label="보관함"
                aria-expanded={isLibraryOpen}
                onClick={() => setIsLibraryOpen(true)}
              >
                <Images aria-hidden className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="생성 옵션"
                aria-expanded={isOptionsOpen}
                onClick={() => setIsOptionsOpen(true)}
              >
                <SlidersHorizontal aria-hidden className="size-4" />
              </Button>
            </div>
          </div>

          {/* 열 내부 스크롤 래퍼 — min-h-0 flex-1 overflow-y-auto(ChatMoreSidebar.tsx:60와 동일). */}
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
            {/* forceMount — 탭을 오가도 입력 중인 프롬프트와 진행 중인 생성 잡 표시(로컬 state)가
                사라지지 않게 언마운트 대신 숨긴다(StudioImagesPage.tsx 옛 관용구 유지).
                변형·인페인트는 disabled라 도달 불가능하므로 그 둘의 TabsContent는 만들지 않는다
                (IT-10 — 빈 껍데기는 도달 불가능한 코드다). */}
            <TabsContent value="generate" forceMount className="flex flex-col gap-6 data-[state=inactive]:hidden">
              <GenerateImagesPromptField />
              <GenerateImagesStyleGrid />
              {/* image-refact-goal-prompt.md IR-16 — 생성 결과는 중앙 하단에 그대로 남긴다. */}
              {jobId !== undefined && (
                <GenerateImagesResultGrid
                  job={jobQuery.data}
                  requestedCount={generateMutation.variables?.count ?? 1}
                  isQueryError={jobQuery.isError}
                />
              )}
            </TabsContent>
          </div>
        </Tabs>

        {/* 우열 — lg 이상만 보인다. */}
        <aside className="hidden w-80 shrink-0 flex-col border-l border-border lg:flex">
          <ImageStudioOptionsRail />
        </aside>
      </GenerateImagesFormProvider>
    </div>
  );
}
