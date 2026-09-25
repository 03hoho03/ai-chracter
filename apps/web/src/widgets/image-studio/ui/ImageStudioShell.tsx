import { useEffect, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useQueryClient } from "@tanstack/react-query";
import { Images, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { cloverKeys, IMAGE_CLOVER_COST } from "@/entities/clover";
import { generatedImagesKeys } from "@/entities/generated-image";
import { useImageJobStatusQuery, type ImageJobStatusResponse } from "@/entities/image-job";
import { useConfirmCloverSpend } from "@/features/confirm-clover-spend";
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

import { formatImageRateLimitMessage, getImageRateLimit } from "../model/imageRateLimitMessage";
import { isImageStudioTab, type ImageStudioTab } from "../model/imageStudioTab";
import { ImageStudioLibraryRail } from "./ImageStudioLibraryRail";
import { ImageStudioOptionsRail } from "./ImageStudioOptionsRail";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

// /studio/images의 3열 셸. widgets/chat-room/ui/ChatRoomView.tsx의
// flex 행을 베낀다: w-full이 없으면 flex 컬럼 자식의 auto 마진 때문에 stretch가 꺼져 폭이
// shrink-to-fit으로 붕괴하고(ChatRoomView.tsx:146 실측), min-h-0은 flex 아이템 기본 min-height:auto를
// 되돌린다 — 없으면 열이 콘텐츠만큼 늘어 페이지 전체가 스크롤된다.
// 크랙 실측: 행은 뷰포트 전체 폭이고 레일이 x=0/x=1132에 붙는다 — 제한되는 건 중앙 콘텐츠뿐
// (768px). 처음 설계가 "max-w는 이 행에 건다"고 정한 건 틀렸다 — 그건 DESIGN.md §Layout
// containers의 대화방 선례를 따른 것인데, 대화방은 본문이 읽기 콘텐츠라 컬럼을 좁히는 게 맞지만
// 여기는 도구라 레일이 가장자리에 붙어야 한다. 그래서 lg 이상에서는 이 행에 max-w를 걸지 않고,
// 중앙 컬럼의 **스크롤 콘텐츠만** max-w-3xl로 감싼다 — 탭 스트립과 border-b는 컬럼 전체 폭이다.
export function ImageStudioShell({
  tab,
  onTabChange,
}: {
  tab: ImageStudioTab;
  onTabChange: (tab: ImageStudioTab) => void;
}) {
  // 시트 열림 상태는 이 셸의 지역 state다. widgets/chat-room의 chatMorePanelOpenAtom은 트리거
  // (ChatMoreNav)가 콘텐츠(ChatMorePanel/ChatMoreSidebar) **안쪽**에 중첩돼 있어 atom으로 건너뛰지만,
  // 여기는 트리거(탭 스트립)와 두 Rail이 전부 이 컴포넌트의 직계 자식이라 prop 한 단이면 닿는다.
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  const [isOptionsOpen, setIsOptionsOpen] = useState(false);

  // features/generate-images가 조각을 한 열로 쌓아 두던 옛 조합 컴포넌트가 갖고 있던 잡 폴링·
  // 제출 로직 — 3열로 조각을 흩는 이 셸이 그 조합을 대신하면서 쓰는 곳이 없어져 지웠고(고아 정리),
  // 로직만 여기로 옮겼다.
  const [jobId, setJobId] = useState<string | undefined>(undefined);
  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(jobId ?? "", jobId !== undefined);

  // 잡이 끝나면 보관함 목록을 무효화한다. 중앙 열은 잡 응답의 job.images로 새 이미지를 이미
  // 보여주지만, 보관함(과 빌더 피커)이 공유하는 `useGeneratedImagesQuery`는 refetchOnWindowFocus
  // 뿐이라 창을 떠났다 돌아오기 전까지 낡은 채로 남았다 — 그 값은 보관함이 "다른 화면"이던 시절에
  // 맞춘 것이고, 3열 개편으로 생성 화면 옆에 상시 노출되면서 갭이 드러났다.
  // 그 쿼리는 gcTime: 0이라 시트가 닫혀 있으면(좁은 화면) 무효화가 no-op이고 다음에 열 때 새로 받는다.
  // failed는 새로 생긴 게 없으므로 제외한다.
  const queryClient = useQueryClient();
  // 확인 게이트의 트리거. `features/generate-images`가 아니라 이
  // 위젯이 만드는 이유는 FSD다(feature끼리 import하지 않는다) — 제출을 소유한 자리도 여기다.
  const confirmCloverSpend = useConfirmCloverSpend();
  const jobStatus = jobQuery.data?.status;
  const hasInvalidatedGalleryRef = useRef(false);
  useEffect(() => {
    if (jobStatus !== "succeeded" || hasInvalidatedGalleryRef.current) return;
    hasInvalidatedGalleryRef.current = true;
    void queryClient.invalidateQueries({ queryKey: generatedImagesKeys.list() });
  }, [jobStatus, queryClient]);

  // 잔액은 보관함과 **다른 시점**에 바뀐다. 위 효과가 `succeeded`만
  // 보는 이유는 실패한 잡이 보관함에 새 이미지를 안 남기기 때문인데, 클로버는 정반대다:
  // 🔴 `blocked`·`input_error`·`failed`·부분 성공이 전부 **환불을 낳으므로**
  // 터미널 상태 전부에서 잔액이 바뀐다. 그래서 효과를 합치지 않고 따로 둔다.
  const hasInvalidatedCloverRef = useRef(false);
  useEffect(() => {
    if (jobStatus !== "succeeded" && jobStatus !== "failed") return;
    if (hasInvalidatedCloverRef.current) return;
    hasInvalidatedCloverRef.current = true;
    void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
  }, [jobStatus, queryClient]);

  async function handleSubmit(values: GenerateImagesFormValues) {
    setJobId(undefined);
    hasInvalidatedGalleryRef.current = false;
    hasInvalidatedCloverRef.current = false;
    await generate(values);
  }

  /** `allowCloverConfirm`은 **무한 루프 차단기**다 — 동의 뒤 재시도는
   * `false`로 들어가므로, 그 재시도가 또 확인 429를 받아도 모달을 다시 띄우지 않고 평범한 실패로
   * 끝난다. 채팅 쪽(`useSendMessage`)과 같은 모양이다.
   *
   * ⚠️ 동의 POST가 실패한 경우는 여기까지 오지 않는다 — `useConfirmCloverSpend`가 그때
   * `"unhandled"`를 돌려주므로 재시도 자체가 없다(그건 진짜 실패라 오류 토스트가 뜬다).
   *
   * 🔴 재시도가 정말로 확인 429를 다시 받는 경로는 **이미지에만 있다**: 토큰 버킷은 시간당
   * 충전이라(`core/rate_limit.py`) 자정에 차지 않으므로, 어제 동의하고 오늘 재시도하면 서버가
   * 다시 확인을 요구한다. 채팅은 일일 키에 KST 날짜가 섞여 자정에 리셋되므로 그 경로 자체가
   * 없다 — 같은 차단기를 두지만 막는 대상이 다르다. */
  async function generate(values: GenerateImagesFormValues, allowCloverConfirm = true) {
    try {
      const response = await generateMutation.mutateAsync(values);
      setJobId(response.jobId);
      // 202 시점에 이미 차감이 끝났다(게이트가 `Depends`에서 깎는다) — 잡이 끝나기를 기다리지
      // 않고 여기서 한 번 반영한다. 위 효과는 그 뒤의 **환불**을 잡는다.
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    } catch (error) {
      // 🔴 **`getImageRateLimit`보다 먼저** 판정해야 한다. 확인 429도
      // 같은 `window: "image"`로 오지만 토스트가 아니라 모달 → 동의 → 재시도로 끝나므로,
      // 순서가 뒤집히면 저 투영이 코드를 모른 채 `undefined`를 주고 일반 오류 토스트가 뜬다.
      // 단가는 BE 게이트와 같은 계산(`payload.count * IMAGE_UNIT_COST`)이다 — 채팅과 달리 장수를
      // 곱한다.
      const confirmOutcome = allowCloverConfirm
        ? await confirmCloverSpend(error, values.count * IMAGE_CLOVER_COST, "image")
        : "unhandled";
      if (confirmOutcome === "retry") {
        await generate(values, false);
        return;
      }
      // 그만두기는 실패가 아니므로 오류 토스트를 띄우지 않는다. 🔴 채팅 3표면과 달리
      // 여기서는 **아무것도 띄우지 않는다**: 채팅은 낙관적 사용자 메시지가 이미 목록에 남아
      // 있어 침묵하면 멈춘 것처럼 읽히지만, 이미지는 화면에 생긴 흔적이 없어 모달을 닫은 것이
      // 곧 완결된 피드백이다(잡도 만들어지지 않아 되돌릴 것도 없다).
      if (confirmOutcome === "declined") return;
      // 429는 두 코드(토큰 부족·큐 만석)가 서로 다음 행동이 달라
      // 문구도 갈린다. 나머지 실패는 기존 분기 그대로다.
      const rateLimit = getImageRateLimit(error);
      if (rateLimit) {
        toast.error(formatImageRateLimitMessage(rateLimit));
        return;
      }
      const apiError = isApiError(error) ? error : undefined;
      toast.error(apiError?.status === 422 ? "입력값을 다시 확인해주세요." : GENERIC_ERROR_MESSAGE);
    }
  }

  return (
    // 랜드마크 <main>은 StudioImagesPage(페이지)가 소유한다 — 이 위젯은 제목 블록과 형제로
    // 놓이므로 여기서 또 <main>을 열면 페이지에 랜드마크가 두 개 생긴다. 행은 lg 미만·이상 구분
    // 없이 항상 뷰포트 전체 폭이다(레일이 가장자리에 붙어야 한다 — 위 배경 주석) — lg 미만의
    // max-w-2xl은 탭바 선이 뷰포트 폭과 어긋나는 문제가 있어(800px에서 x=64~672px, 2026-09-14
    // 사용자 피드백) 중앙 컬럼의 스크롤 콘텐츠 쪽으로 옮겼다.
    <div className="flex w-full min-h-0 flex-col lg:h-below-header lg:flex-row">
      {/* 좌열 — lg 이상만 보인다(그림자 없음, 경계는 border-r 한 줄, DESIGN.md Flat-at-Rest). */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
        <ImageStudioLibraryRail isOpen={isLibraryOpen} onOpenChange={setIsLibraryOpen} />
      </aside>

      {/* GenerateImagesFormProvider는 중앙(Prompt/Style/Result)과
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
          {/* 탭 스트립은 아래 콘텐츠와 달리 max-width를 걸지 않는다 — 선과 마찬가지로 컬럼 전체
              폭을 쓴다. 한때 콘텐츠와 같은 max-w-3xl로 묶었는데, 1920px에서 탭이 콘텐츠보다
              296px 바깥에 서서 어긋나 보였다(2026-09-14 사용자 피드백). 탭은 읽는 콘텐츠가
              아니라 그 컬럼의 크롬이라 컬럼 경계를 따르는 쪽이 맞다. 시트 트리거 2개도 이
              행에 있어 컬럼 오른쪽 끝에 선다 — lg 미만에서만 보이므로 폭 제한과 무관하다.
              px-3 패딩은 여기 둔다(선은 패딩 밖, 즉 컬럼 전체를 가로지른다) — 세로 패딩은 주지
              않는다: 행 높이가 TabsTrigger/시트 트리거의 36px과 같아져야 활성 탭의 밑줄
              (tabs.tsx의 after:bottom-[-5px])이 탭바 하단 border에 닿는다(2026-09-14 사용자
              피드백). 시트 트리거도 같은 36px이라 세로 패딩 0에서 잘리지 않는다. */}
          <div className="shrink-0 border-b border-border">
            <div className="flex w-full items-center justify-between gap-2 px-3">
              {/* h-12 — 프리미티브 기본 h-9(36px)를 덮는다. 세로 패딩을 걷고 나니 헤더(57px) 옆에서
                  탭바가 눌려 보였다(2026-09-14 사용자 피드백). 헤더와 같은 h-14로 올리지 않는 이유는
                  두 줄이 같은 두께면 크롬이 두 겹으로 읽히기 때문이다 — 탭은 컬럼 내부 요소지 크롬이
                  아니다. **밑줄 조건은 이 변경으로 깨지지 않는다**: TabsTrigger가
                  `h-[calc(100%-1px)]`로 부모를 따라가므로 밑줄(`after:bottom-[-5px]`)은 리스트 높이와
                  무관하게 항상 리스트 바닥 +1px에 선다. 행에 세로 패딩이 없으므로 그 자리가 곧
                  탭바 하단 border다. 시트 트리거(36px)는 items-center로 가운데 정렬된다. */}
              <TabsList variant="line" className="group-data-horizontal/tabs:h-12">
                <TabsTrigger value="generate">생성</TabsTrigger>
                {/* 저장소 최초의 disabled 탭. GenerateImagesStyleGrid의
                    "· 준비 중" 표기와 같은 어법을 접근 가능한 이름에도 남긴다. */}
                <TabsTrigger value="transform" disabled>
                  변형 · 준비 중
                </TabsTrigger>
                <TabsTrigger value="inpaint" disabled>
                  인페인트 · 준비 중
                </TabsTrigger>
              </TabsList>

              {/* 시트 트리거 2개. 크랙은 size-12(48px)지만 우리
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
              overflow-y-auto는 컬럼 전체 폭에 두고 안쪽 내용만 max-w-2xl(lg 이상 max-w-3xl)로
              묶는다 — 스크롤바가 콘텐츠가 아니라 컬럼 가장자리에 붙어야 한다(위 탭 스트립과 같은
              이유). lg 미만의 max-w-2xl은 행 쪽에 걸려 있던 것을 여기로 옮겼다(위 배경 주석). */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-6 lg:max-w-3xl">
              {/* forceMount — 탭을 오가도 입력 중인 프롬프트와 진행 중인 생성 잡 표시(로컬 state)가
                  사라지지 않게 언마운트 대신 숨긴다(StudioImagesPage.tsx 옛 관용구 유지).
                  변형·인페인트는 disabled라 도달 불가능하므로 그 둘의 TabsContent는 만들지 않는다
                  (빈 껍데기는 도달 불가능한 코드다). */}
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
          <ImageStudioOptionsRail isOpen={isOptionsOpen} onOpenChange={setIsOptionsOpen} />
        </aside>
      </GenerateImagesFormProvider>
    </div>
  );
}

type ImageStudioGenerateTabContentProps = {
  jobId: string | undefined;
  jobData: ImageJobStatusResponse | undefined;
  requestedCount: number;
  isJobQueryError: boolean;
};

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
}: ImageStudioGenerateTabContentProps) {
  const { unavailableReason, onRetry } = useGenerateImagesSubmit();

  if (unavailableReason) {
    return <GenerateImagesUnavailableState reason={unavailableReason} onRetry={onRetry} />;
  }

  return (
    <>
      <GenerateImagesPromptField />
      <GenerateImagesStyleGrid />
      {/* 생성 결과는 중앙 하단에 그대로 남긴다. */}
      {jobId !== undefined && (
        <GenerateImagesResultGrid job={jobData} requestedCount={requestedCount} isQueryError={isJobQueryError} />
      )}
    </>
  );
}
