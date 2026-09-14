import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useAtom } from "jotai";
import { Images, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { useImageJobStatusQuery, type ImageJobStatusResponse } from "@/entities/image-job";
import {
  GenerateImagesFormProvider,
  GenerateImagesPromptField,
  GenerateImagesResultGrid,
  GenerateImagesStyleGrid,
  GenerateImagesUnavailableState,
  useGenerateImagesMutation,
  useGenerateImagesSubmit,
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
// 되돌린다 — 없으면 열이 콘텐츠만큼 늘어 페이지 전체가 스크롤된다.
// 크랙 §0-1 실측: 행은 뷰포트 전체 폭이고 레일이 x=0/x=1132에 붙는다 — 제한되는 건 중앙 콘텐츠뿐
// (§0-3, 768px). IR-2/IT-7이 "max-w는 이 행에 건다"고 정한 건 틀렸다 — 그건 DESIGN.md §Layout
// containers의 대화방 선례를 따른 것인데, 대화방은 본문이 읽기 콘텐츠라 컬럼을 좁히는 게 맞지만
// 여기는 도구라 레일이 가장자리에 붙어야 한다. 그래서 lg 이상에서는 이 행에 max-w를 걸지 않고,
// 중앙 컬럼 안쪽 두 블록만 max-w-3xl로 감싼다.
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
    // 놓이므로 여기서 또 <main>을 열면 페이지에 랜드마크가 두 개 생긴다. lg 미만은 모바일 단일
    // 컬럼이라 mx-auto max-w-2xl을 유지하고, lg 이상은 max-w-7xl·mx-auto를 걷어 행이 뷰포트
    // 전체 폭을 쓰게 한다(레일이 가장자리에 붙어야 한다 — 위 배경 주석).
    <div className="mx-auto flex w-full min-h-0 max-w-2xl flex-col lg:mx-0 lg:h-below-header lg:max-w-none lg:flex-row">
      {/* 좌열 — lg 이상만 보인다(그림자 없음, 경계는 border-r 한 줄, DESIGN.md Flat-at-Rest). */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
        <ImageStudioLibraryRail />
      </aside>

      {/* image-refact-techspec.md IT-9 — GenerateImagesFormProvider는 중앙(Prompt/Style/Result)과
          우열(Options) 양쪽의 공통 조상이어야 폼 context가 닿는다(React context는 DOM 위치와
          무관). 좌열(보관함)은 그 바깥에 둔다 — 폼 context가 전혀 필요 없고, 모델 목록을 못
          불러온 상태에서도 이미 만든 보관함은 계속 열 수 있어야 한다.
          이 프로바이더는 더 이상 "이용 불가" 판정으로 children을 통째로 갈아치우지 않는다
          (브라우저 실검증 회귀 수정) — 탭 스트립·시트 트리거·좌우열 껍데기는 어떤 상태에서도
          항상 남고, 판정 결과만 context로 내려 중앙 TabsContent 안(ImageStudioGenerateTabContent)
          에서만 대체 UI로 바꿔 낀다. */}
      <GenerateImagesFormProvider onSubmit={handleSubmit}>
        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (isImageStudioTab(value)) onTabChange(value);
          }}
          className="flex min-h-0 min-w-0 flex-1 flex-col gap-0"
        >
          {/* 크랙 §0-3 실측대로 border-b는 컬럼 전체 폭을 가로지르고, 안쪽 내용만 max-w-3xl(768px)로
              묶는다 — DESIGN.md §Layout containers의 대화방 처방(헤더 border-b를 컬럼 div에 걸어
              선이 뷰포트가 아니라 컬럼을 따르게 한다)과 반대 방향으로, 여기선 선이 컬럼을 따르고
              내용만 좁힌다. px-4 sm:px-6 패딩도 안쪽 래퍼에 둔다 — 그래야 1024px처럼 컬럼이
              768px보다 좁을 때도 콘텐츠가 가장자리에 붙지 않는다. */}
          <div className="shrink-0 border-b border-border">
            <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-2 px-4 py-3 sm:px-6">
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
                  data-image-studio-trigger="library"
                  onClick={() => setIsLibraryOpen(true)}
                >
                  <Images aria-hidden className="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="생성 옵션"
                  aria-expanded={isOptionsOpen}
                  data-image-studio-trigger="options"
                  onClick={() => setIsOptionsOpen(true)}
                >
                  <SlidersHorizontal aria-hidden className="size-4" />
                </Button>
              </div>
            </div>
          </div>

          {/* 열 내부 스크롤 래퍼 — min-h-0 flex-1 overflow-y-auto(ChatMoreSidebar.tsx:60와 동일).
              overflow-y-auto는 컬럼 전체 폭에 두고 안쪽 내용만 max-w-3xl로 묶는다 — 스크롤바가
              콘텐츠가 아니라 컬럼 가장자리에 붙어야 한다(위 탭 스트립과 같은 이유). */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
              {/* forceMount — 탭을 오가도 입력 중인 프롬프트와 진행 중인 생성 잡 표시(로컬 state)가
                  사라지지 않게 언마운트 대신 숨긴다(StudioImagesPage.tsx 옛 관용구 유지).
                  변형·인페인트는 disabled라 도달 불가능하므로 그 둘의 TabsContent는 만들지 않는다
                  (IT-10 — 빈 껍데기는 도달 불가능한 코드다). */}
              <TabsContent value="generate" forceMount className="flex flex-col gap-6 data-[state=inactive]:hidden">
                <ImageStudioGenerateTabContent
                  jobId={jobId}
                  jobData={jobQuery.data}
                  requestedCount={generateMutation.variables?.count ?? 1}
                  isJobQueryError={jobQuery.isError}
                />
              </TabsContent>
            </div>
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

// 브라우저 실검증 회귀 수정 — GenerateImagesFormProvider가 더 이상 early return하지 않으므로
// (파일 상단 주석), "이용 불가"일 때 프롬프트·스타일·결과 대신 대체 UI를 꽂는 이 판정은 중앙
// TabsContent **안**에서만 일어난다. 이 함수가 useGenerateImagesSubmit()을 부르려면 그 자체가
// GenerateImagesFormProvider의 자손이어야 한다 — ImageStudioShell 본문에서 그냥 호출하면 아직
// FormProvider가 만들어지기 전 트리를 읽어 항상 실패한다.
function ImageStudioGenerateTabContent({
  jobId,
  jobData,
  requestedCount,
  isJobQueryError,
}: {
  jobId: string | undefined;
  jobData: ImageJobStatusResponse | undefined;
  requestedCount: number;
  isJobQueryError: boolean;
}) {
  const { unavailableReason, onRetry } = useGenerateImagesSubmit();

  if (unavailableReason) {
    return <GenerateImagesUnavailableState reason={unavailableReason} onRetry={onRetry} />;
  }

  return (
    <>
      <GenerateImagesPromptField />
      <GenerateImagesStyleGrid />
      {/* image-refact-goal-prompt.md IR-16 — 생성 결과는 중앙 하단에 그대로 남긴다. */}
      {jobId !== undefined && (
        <GenerateImagesResultGrid job={jobData} requestedCount={requestedCount} isQueryError={isJobQueryError} />
      )}
    </>
  );
}
