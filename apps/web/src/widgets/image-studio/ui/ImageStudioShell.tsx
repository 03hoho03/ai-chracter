import { useEffect, useRef, useState, type RefObject } from "react";
import { flushSync } from "react-dom";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useQueryClient } from "@tanstack/react-query";
import { Images, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { cloverKeys, IMAGE_CLOVER_COST } from "@/entities/clover";
import { generatedImagesKeys } from "@/entities/generated-image";
import { useImageJobStatusQuery, type ImageJobStatusResponse } from "@/entities/image-job";
import { imageModelKeys } from "@/entities/image-model";
import { useConfirmCloverSpend } from "@/features/confirm-clover-spend";
import {
  GenerateImagesFormProvider,
  GenerateImagesPromptField,
  GenerateImagesReferenceField,
  GenerateImagesResultGrid,
  GenerateImagesStyleSummaryButton,
  GenerateImagesUnavailableState,
  useGenerateImagesMutation,
  useGenerateImagesSubmit,
  type GenerateImagesFormValues,
  type GenerateImagesSubmitHelpers,
  type ResultShape,
} from "@/features/generate-images";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { isApiError } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

import { formatImageRateLimitMessage, getImageRateLimit } from "../model/imageRateLimitMessage";
import { formatReferenceImageErrorMessage, getReferenceImageError } from "../model/referenceImageError";
import { isImageStudioTab, type ImageStudioTab } from "../model/imageStudioTab";
import { ImageStudioLibraryRail } from "./ImageStudioLibraryRail";
import { ImageStudioOptionsRail, type OptionsSheetEntry } from "./ImageStudioOptionsRail";

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
  // 시트 열림 상태는 이 셸의 지역 state다. widgets/chat-room의 chatSidePanelAtom은 트리거
  // (ChatMoreNav)가 콘텐츠(ChatMorePanel/ChatMoreSidebar) **안쪽**에 중첩돼 있어 atom으로 건너뛰지만,
  // 여기는 트리거(탭 스트립·중앙의 스타일 선택 버튼)와 두 Rail이 전부 이 컴포넌트 아래라 prop으로
  // 닿는다 — 가장 깊은 스타일 선택 버튼도 중앙 탭 내용 컴포넌트를 거치는 두 단이다.
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  // 옵션 시트는 진입점이 둘(탭 줄의 옵션 아이콘, 중앙의 스타일 선택 버튼)이라 열림 여부와 함께 "누가
  // 열었나"를 쥔다 — `aria-expanded`는 연 트리거에만 참이고, 시트는 그 값으로 열 때 보낼 자리와 닫을 때
  // 돌려줄 트리거를 고른다. 닫아도 `entry`를 지우지 않는 것은 닫힘 포커스 처리기가 닫히는 그 순간에
  // 이 값을 읽기 때문이다.
  const [optionsSheet, setOptionsSheet] = useState<{ isOpen: boolean; entry: OptionsSheetEntry }>({
    isOpen: false,
    entry: "options",
  });
  // 202 직후 스크롤할 결과 영역.
  const resultAreaRef = useRef<HTMLDivElement>(null);

  // features/generate-images가 조각을 한 열로 쌓아 두던 옛 조합 컴포넌트가 갖고 있던 잡 폴링·
  // 제출 로직 — 3열로 조각을 흩는 이 셸이 그 조합을 대신하면서 쓰는 곳이 없어져 지웠고(고아 정리),
  // 로직만 여기로 옮겼다.
  //
  // 결과 영역이 보이는 잡은 **202를 받은 제출** 하나다. 그 순간의 잡 id와 비율·개수를 함께 잡아 두고,
  // 다음 제출이 202를 받을 때만 바꾼다 — 확인 모달을 거절했거나 429·참조 거절·422로 요청이 실패하면
  // 잡이 생기지 않았으므로 직전 결과가 그대로 남는다. 비율·개수를 `generateMutation.variables`에서
  // 읽지 않는 이유도 같다: 그 값은 실패한 제출로도 덮여, 직전 결과가 방금 거절된 비율로 다시 그려진다.
  const [submission, setSubmission] = useState<JobSubmission | undefined>(undefined);
  const generateMutation = useGenerateImagesMutation();
  const jobQuery = useImageJobStatusQuery(submission?.jobId ?? "", submission !== undefined);

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

  async function handleSubmit(values: GenerateImagesFormValues, helpers: GenerateImagesSubmitHelpers) {
    await generate(values, helpers);
  }

  // 참조 피커는 다른 feature 슬라이스라 폼 슬라이스가 직접 부르지 않고 이 위젯이 주입한다(확인 게이트와
  // 같은 이유). 여기는 이미 생성 화면이라 빌더용 "새로 생성하기" 새 탭 링크를 숨기고 문구를 참조용으로 바꾼다.
  function pickReferenceImage() {
    return GeneratedImagePickerModal.call({
      title: "참조할 이미지 고르기",
      description: "내가 만든 이미지 중 하나를 골라 참조로 써요.",
      emptyHint: "이미지를 생성하면 여기에서 고를 수 있어요.",
      shouldShowCreateLink: false,
    });
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
  async function generate(
    values: GenerateImagesFormValues,
    helpers: GenerateImagesSubmitHelpers,
    allowCloverConfirm = true,
  ) {
    try {
      const response = await generateMutation.mutateAsync({
        values,
        isReferenceEnabled: helpers.isReferenceEnabled,
      });
      // 위 두 무효화 효과의 "이 잡에서 이미 했다" 표시는 지켜보는 잡 하나에 묶인 값이라, 지켜보는 잡이
      // 바뀌는 이 자리(202)에서 함께 되돌린다. 요청이 실패하면 잡이 바뀌지 않으므로 표시도 그대로다.
      hasInvalidatedGalleryRef.current = false;
      hasInvalidatedCloverRef.current = false;
      // 결과 영역을 시야로 데려온다 — 생성 버튼이 화면 위쪽에 있어 결과가 화면 아래로 밀려 있을 수 있다.
      // `flushSync`로 새 제출을 먼저 커밋하는 것은 제출한 비율의 스켈레톤 높이로 판정해야 직전 결과와
      // 비율이 다를 때 모자라거나 지나치게 밀지 않기 때문이다. `nearest`라 이미 다 보이면 움직이지 않고,
      // 넘친 만큼만 민다(좁은 화면은 문서가, 넓은 화면은 중앙 스크롤러가 움직인다). 포커스는 누른
      // 생성 버튼에 그대로 둔다. 모션 감소 설정이면 즉시 옮긴다.
      flushSync(() => {
        setSubmission({ jobId: response.jobId, aspectRatio: values.aspectRatio, count: values.count });
      });
      resultAreaRef.current?.scrollIntoView({
        block: "nearest",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
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
        await generate(values, helpers, false);
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
      // 참조 거절은 422 분기보다 **먼저** 본다 — 422 문구("입력값을 다시 확인해주세요")로는 무엇을
      // 고칠지 모른다. 둘 다 참조를 비운다. 없어진 참조는 다시 고르면 되므로 참조 필드 아래에 오류로
      // 남기고, 서버가 참조를 껐다면 행 자체가 사라지므로(모델 목록을 다시 받아 숨긴다) 오류를 걸 필드가
      // 없어 토스트로 알린다.
      const referenceError = getReferenceImageError(error);
      if (referenceError !== undefined) {
        switch (referenceError) {
          case "not_found":
            helpers.clearReference(formatReferenceImageErrorMessage(referenceError));
            return;
          case "disabled":
            helpers.clearReference();
            void queryClient.invalidateQueries({ queryKey: imageModelKeys.all });
            toast.error(formatReferenceImageErrorMessage(referenceError));
            return;
          default:
            return assertNever(referenceError);
        }
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
      {/* GenerateImagesFormProvider는 좌열(보관함)·중앙(프롬프트·참조·결과)·우열(옵션·스타일) 셋 모두의
          공통 조상이다(React context는 DOM 위치와 무관해 포털로 뜨는 시트 안에도 닿는다). 보관함까지
          감싸는 것은 보관함에서 연 이미지를 참조로 넣으려면 보관함도 폼에 닿아야 하기 때문이다.
          모델 목록을 못 불러온 상태에서도 이미 만든 보관함은 계속 열 수 있어야 하는데, 이 프로바이더는
          "이용 불가" 판정으로 children을 갈아치우지 않고 늘 그대로 그리므로(브라우저 실검증 회귀
          수정) 감싸도 그 성질이 유지된다 — 탭 스트립·시트 트리거·좌우열 껍데기는 어떤 상태에서도
          남고, 판정 결과만 context로 내려 중앙 TabsContent 안(ImageStudioGenerateTabContent)에서만
          대체 UI로 바꿔 낀다. */}
      <GenerateImagesFormProvider onSubmit={handleSubmit} onPickReference={pickReferenceImage}>
        {/* 좌열 — lg 이상만 보인다(그림자 없음, 경계는 border-r 한 줄, DESIGN.md Flat-at-Rest). */}
        <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
          <ImageStudioLibraryRail isOpen={isLibraryOpen} onOpenChange={setIsLibraryOpen} />
        </aside>

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
                  aria-expanded={optionsSheet.isOpen && optionsSheet.entry === "options"}
                  data-image-studio-trigger="options"
                  onClick={() => setOptionsSheet({ isOpen: true, entry: "options" })}
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
              {/* forceMount — 탭이 여럿이던 때, 다른 탭으로 가도 입력 중인 프롬프트와 진행 중인 생성 잡
                  표시(로컬 state)가 사라지지 않게 언마운트 대신 숨기던 관용구다(StudioImagesPage.tsx 옛
                  관용구). 지금은 탭이 '생성' 하나라 숨겨지는 일이 없지만, 탭을 다시 붙이면 같은 이유로
                  필요해서 남겨 둔다. */}
              <TabsContent value="generate" forceMount className="flex flex-col gap-6 data-[state=inactive]:hidden">
                <ImageStudioGenerateTabContent
                  isStyleSheetOpen={optionsSheet.isOpen && optionsSheet.entry === "style"}
                  onOpenStyleSheet={() => setOptionsSheet({ isOpen: true, entry: "style" })}
                  resultAreaRef={resultAreaRef}
                  submission={submission}
                  jobData={jobQuery.data}
                  isJobQueryError={jobQuery.isError}
                />
              </TabsContent>
            </div>
          </div>
        </Tabs>

        {/* 우열 — lg 이상만 보인다. */}
        <aside className="hidden w-80 shrink-0 flex-col border-l border-border lg:flex xl:w-96">
          <ImageStudioOptionsRail
            isOpen={optionsSheet.isOpen}
            entry={optionsSheet.entry}
            onOpenChange={(isOpen) => setOptionsSheet((previous) => ({ ...previous, isOpen }))}
          />
        </aside>
      </GenerateImagesFormProvider>
    </div>
  );
}

/** 202를 받은 제출. 결과 영역은 이 잡의 진행을 이 비율·개수 모양으로 그린다. */
type JobSubmission = ResultShape & { jobId: string };

type ImageStudioGenerateTabContentProps = {
  isStyleSheetOpen: boolean;
  onOpenStyleSheet: () => void;
  resultAreaRef: RefObject<HTMLDivElement | null>;
  submission: JobSubmission | undefined;
  jobData: ImageJobStatusResponse | undefined;
  isJobQueryError: boolean;
};

// 브라우저 실검증 회귀 수정 — GenerateImagesFormProvider가 더 이상 early return하지 않으므로
// (파일 상단 주석), "이용 불가"일 때 프롬프트·참조·스타일 선택 버튼·결과 대신 대체 UI를 꽂는 이 판정은 중앙
// TabsContent **안**에서만 일어난다. 이 함수가 useGenerateImagesSubmit()을 부르려면 그 자체가
// GenerateImagesFormProvider의 자손이어야 한다 — ImageStudioShell 본문에서 그냥 호출하면 아직
// FormProvider가 만들어지기 전 트리를 읽어 항상 실패한다.
function ImageStudioGenerateTabContent({
  isStyleSheetOpen,
  onOpenStyleSheet,
  resultAreaRef,
  submission,
  jobData,
  isJobQueryError,
}: ImageStudioGenerateTabContentProps) {
  const { unavailableReason, onRetry } = useGenerateImagesSubmit();

  if (unavailableReason) {
    return <GenerateImagesUnavailableState reason={unavailableReason} onRetry={onRetry} />;
  }

  return (
    <>
      <GenerateImagesPromptField />
      <GenerateImagesReferenceField />
      {/* 좁은 화면에서 스타일은 옵션 시트 안에 있어, 고른 스타일과 비율·개수를 결과 바로 위에 요약해 보이고
          누르면 그 시트의 스타일 자리로 연다. 넓은 화면은 우열에 스타일이 늘 보여 숨긴다. 이용 불가
          화면에는 고를 스타일이 없어 이 버튼도 없다(위 early return) — 그래서 시트의 닫힘 포커스는 이
          버튼이 없으면 옵션 아이콘으로 물러선다. */}
      <GenerateImagesStyleSummaryButton
        aria-expanded={isStyleSheetOpen}
        data-image-studio-trigger="style"
        onClick={onOpenStyleSheet}
        className="lg:hidden"
      />
      {/* 결과 영역은 그 아래에 늘 있다 — 첫 생성 전에는 빈 상태로 자리를 잡아 두어, 생성을 누른 자리에서
          눈을 옮기지 않고 진행과 결과를 본다. 감싼 div는 202 직후 스크롤의 대상이고, 스크롤 여백은
          좁은 화면에서 창이 스크롤되며 sticky 헤더(h-14) 아래로 숨지 않게 위를 80px, 넓은 화면에서는
          중앙 스크롤러 위쪽이 이미 헤더 아래라 24px만 띄운다. 아래 24px은 결과가 화면 바닥에 붙지 않게 한다. */}
      <div ref={resultAreaRef} className="scroll-mt-20 scroll-mb-6 lg:scroll-mt-6">
        <GenerateImagesResultGrid shape={submission} job={jobData} isQueryError={isJobQueryError} />
      </div>
    </>
  );
}
