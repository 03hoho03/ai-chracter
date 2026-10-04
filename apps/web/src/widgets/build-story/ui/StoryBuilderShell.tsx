import { useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent } from "@ai-character-chat/ui/components/tabs";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { Grid3x3 } from "lucide-react";
import { FormProvider, useForm, useWatch, type FieldErrors, type Resolver } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, type StoryDraftContent } from "@/entities/content";
import type { MediaTagImages } from "@/entities/media-book";
import type { PreviewStartPayload } from "@/entities/preview-session";
import {
  storyBuilderSchema,
  collapseStartingSetupListPath,
  ENDING_RULE_STAT_NOT_FOUND_MESSAGE,
  formToServer,
  isEndingRuleStatNotFoundError,
  isMediaBookPositionTakenError,
  locateSituationNotePublishError,
  MEDIA_BOOK_POSITION_TAKEN_MESSAGE,
  mediaBookPublishErrorMessage,
  mediaBookSchema,
  SELECTED_STARTING_SETUP,
  serverToForm,
  SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE,
  situationNoteStatNotFoundPaths,
  STARTING_SETUP_SCOPE,
  storyAutosaveErrorMessage,
  STORY_COLLAPSIBLE_LISTS,
  STORY_FIELD_LABELS,
  STORY_MISSING_FIELD_FORM_PATH,
  STORY_MISSING_FIELD_LABELS,
  STORY_STARTING_SETUP_LIST_LABELS,
  STORY_TABS,
  toMediaBookPreviewImages,
  type StoryBuilderFormValues,
  type StoryBuilderTab,
} from "@/features/build-story";
import {
  BuilderLayout,
  BuilderTabStrip,
  BuilderTopBar,
  BuilderTopBarActions,
  BuilderUiStateContext,
  errorItemKeys,
  errorParentItemId,
  errorTabs,
  fieldLabelByFormPath,
  firstErrorLocation,
  flattenFieldErrorPaths,
  getFilterRejectionReason,
  getMissingFields,
  getPublishFailureMessage,
  invalidFieldsMessage,
  missingFieldsMessage,
  resolveProfileImageUrl,
  useAutosave,
  useCreateBuilderUiState,
  useDraftPersistence,
  useFocusFirstError,
  useProfileImageLocalUrl,
} from "@/features/build-common";
import { AppealModal } from "@/features/submit-appeal";
import { creationGuidePath } from "@/shared/config/creationGuide";

import { useMediaBookThumbnailsStore } from "../model/useMediaBookThumbnailsStore";
import { EndingTab } from "./EndingTab";
import { KeywordNoteTab } from "./KeywordNoteTab";
import { MediaBookGridPane } from "./MediaBookGridPane";
import { MediaBookSelectionProvider } from "./MediaBookSelectionProvider";
import { MediaBookTab } from "./MediaBookTab";
import { MediaBookThumbnailsProvider } from "./MediaBookThumbnailsProvider";
import { ProfileTab } from "./ProfileTab";
import { RegistrationTab } from "./RegistrationTab";
import { SettingTab } from "./SettingTab";
import { ShortcutTab } from "./ShortcutTab";
import { SituationNoteTab } from "./SituationNoteTab";
import { StartingSetupTab } from "./StartingSetupTab";
import { StatTab } from "./StatTab";

type StoryBuilderShellProps = {
  draft: StoryDraftContent;
  draftId: string | undefined;
  renderPreview: (args: {
    kind: "card" | "chat";
    getPayload: () => PreviewStartPayload;
    getMediaBookImages: () => MediaTagImages;
    onClose: () => void;
    thumbnailUrl: string | null;
  }) => ReactNode;
};

// 탭 목록은 features/build-story/model/tabs.ts(STORY_TABS)가 단일 소스다 —
// fields(에러 탭 매칭용 경로 프리픽스)·preview가 이 배열에 함께 실려 있다.
const TABS = STORY_TABS;

// 서버 400 의 필드명 → 라벨·폼 경로 두 맵은 features/build-story 의 publishMissingFields.ts 에 있다. 클라 검증 실패
// 경로(handlePublishInvalid)가 들고 있는 건 서버 필드명이 아니라 폼 경로라, 그 두 맵에서 "폼 경로 → 라벨"을
// 파생시킨다 — 세 번째 맵을 손으로 적지 않는다.
const MISSING_FIELD_LABEL_BY_FORM_PATH = fieldLabelByFormPath(
  STORY_MISSING_FIELD_FORM_PATH,
  STORY_MISSING_FIELD_LABELS,
);

// 클라 검증의 미디어 북 오류는 항목마다 경로가 달라(`mediaBook.people.0.name` 등) 위 맵처럼 하나씩 적을 수 없다 — 토스트에서는
// 경로를 `mediaBook` 하나로 접어 "미디어 북"으로 부른다(서버 400 은 미디어 북 키가 둘로 정해져 있어 접지 않고 라벨 맵에서
// 찾는다). 미디어 북 탭은 폼 오류를 항목 옆에 그리지 않는다: 화면이 규칙에 맞지 않는 값을 폼에 넣지 않으므로(이름 오류는
// 입력칸이 폼 밖에서 따로 보인다) 이 경로에 닿는 것은 서버만 아는 상태뿐이고, 그때 사용자가 보는 것은 이 토스트와 탭 스트립의 오류 표시다.
const MEDIA_BOOK_PATH = "mediaBook";
const MEDIA_BOOK_LABEL = "미디어 북";

/** 탭 단일 useForm 셸. 자동저장/발행/
 * 미리보기를 CharacterBuilderShell.tsx와 동일한 방식으로 연동한다.
 *
 * `draftId`는 아직 서버에 없는 초안이면 undefined다 — 첫 저장이 초안을 만들고 URL을 바꾼다. */
export function StoryBuilderShell({ draft, draftId, renderPreview }: StoryBuilderShellProps) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<StoryBuilderTab>("profile");
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  // 폼 컨벤션(중복 제출 방지는 `isSubmitting`)에서 의도적으로 벗어난다 — `form.formState.isSubmitting`은
  // 검증 구간까지 포함해 true가 되는데 발행 버튼은 네이티브 `disabled`라 유효성 실패 때마다 포커스가
  // body로 떨어진다. onValid 경로(handlePublish)에서만 켜지는 로컬 state로 대신한다.
  const [isPublishing, setIsPublishing] = useState(false);
  const [rejectionReason, setRejectionReason] = useState<string>();
  // mode/reValidateMode/shouldUnregister를 명시하지 않는다 — RHF 기본값(제출 전엔 조용히, 제출 후엔
  // onChange 재검증)이 이미 "발행 시도 후에는 고치는 즉시 에러가 풀린다"는 요구와 정확히 같다.
  // 기본값을 그대로 두는 것 자체가 의도된 결정이다.
  const form = useForm<StoryBuilderFormValues>({
    // storySetting.promptTemplate/developmentExamples 등 `.default()`가 붙은 필드는 zod의 input
    // 타입과 output 타입이 갈린다 — zodResolver()는 `Resolver<Input, any, Output>`을 돌려주는데
    // useForm<StoryBuilderFormValues>(output 하나로 폼 전체를 표현)는 `Resolver<Output, any, Output>`
    // 을 요구해 타입이 어긋난다. RHF는 세 번째 제네릭(TTransformedValues)으로 이 간극을 메우도록
    // 설계돼 있지만, 그러면 `getValues()`/`formToServer` 전체가 매 defaultable 필드마다 옵셔널
    // 타입으로 번진다(자동저장·미리보기 경로까지). 런타임에는 안전하다 — defaultValues(serverToForm)가
    // 이 필드들을 항상 채워 넘기고 이후 어떤 입력도 그걸 undefined로 되돌리지 않는다.
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions -- 위 사유(zod .default()/RHF Resolver 제네릭의 구조적 한계)
    resolver: zodResolver(storyBuilderSchema) as Resolver<StoryBuilderFormValues>,
    defaultValues: serverToForm(draft),
  });

  // 대표 이미지 칸과 미리보기 카드가 같은 그림, 곧 폼이 지금 가진 그림을 보이도록 표시 주소를 여기서 한 번 정해
  // 둘에 내려 준다. 초안 응답의 주소는 마지막 저장이 본 그림일 뿐이라 그대로 쓰면 저장이 끝날 때까지 카드가 옛
  // 그림에 머문다. 방금 올리거나 고른 그림의 주소를 탭이 아니라 셸이 쥐는 이유는 탭을 옮기면 탭 본문이
  // 언마운트되기 때문이다. 셸은 폼 값 변화를 구독하지 않으므로(자동저장의 `form.watch` 콜백 구독은 재렌더를
  // 일으키지 않는다) 이 필드만 따로 구독한다.
  const profileImage = useWatch({ control: form.control, name: "profile.image" });
  const profileImageLocal = useProfileImageLocalUrl();
  const thumbnailUrl = resolveProfileImageUrl({ image: profileImage, local: profileImageLocal.local, draft });

  const mediaBookThumbnails = useMediaBookThumbnailsStore(draft);

  const { saveDraft } = useDraftPersistence({ type: "story", draftId });
  const publishMutation = usePublishContentMutation();

  // 발행 실패 시 첫 에러 필드로 이동한다(탭이 다르면 먼저 전환). tabId는
  // firstErrorLocation이 TABS 근거로 돌려주는 값이라 항상 유효하지만, 타입은 string이라 좁힘이
  // 필요하다(`as` 대신 술어 — isStoryBuilderTab, 파일 하단).
  const focusFirstError = useFocusFirstError({
    form,
    activeTab,
    setActiveTab: (tabId) => {
      if (isStoryBuilderTab(tabId)) setActiveTab(tabId);
    },
  });

  // 반복 항목의 열림과 스탯·상황 노트·엔딩 탭이 함께 보는 고른 시작설정. 탭 본문은 탭을 바꿀 때 언마운트되므로 셸이 쥐고, 폼 값이
  // 아니라서 자동저장·검증과 무관하다.
  const uiState = useCreateBuilderUiState();

  // 발행 실패 때 첫 오류로 가기 전에 오류를 품은 항목을 펼치고(오류가 풀려도 펼친 채 둔다 — 고치는 키 입력에 접히면
  // 포커스가 body 로 떨어진다), 스탯·상황 노트·엔딩 탭이 오류가 있는 시작설정을 보이게 바꿔 둔다. 포커스보다 먼저여야 그 필드가
  // 숨거나 그려지지 않은 채로 포커스를 받지 않는다. 서버 거절은 목록·섹션 경로만 가리켜 펼칠 항목이 없을 수 있다 — 그때는
  // 목록 머리의 오류 문장이 맡는다.
  function revealAndFocusFirstError(errors: FieldErrors<StoryBuilderFormValues>) {
    const location = firstErrorLocation(errors, TABS);
    const values = form.getValues();
    uiState.open(errorItemKeys(errors, values, STORY_COLLAPSIBLE_LISTS, TABS));
    const setupId = errorParentItemId(errors, values, STARTING_SETUP_SCOPE, TABS, location?.fieldPath);
    if (setupId !== undefined) uiState.select(SELECTED_STARTING_SETUP, setupId);
    focusFirstError(location);
  }

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      // `watch` 콜백이 주는 값은 `DeepPartial`이다(미등록 필드가 있을 수 있어서). 구독은 **변경
      // 신호**로만 쓰고 값은 `getValues()`로 읽는다 — 단언 없이 완전한 폼 타입이 나온다.
      const subscription = form.watch(() => cb(form.getValues()));
      return () => subscription.unsubscribe();
    },
    formToServer,
    save: saveDraft,
    flushOnUnmount: () => draftId !== undefined,
    errorMessage: storyAutosaveErrorMessage,
  });

  async function handleSaveNow() {
    const values = form.getValues();
    try {
      await saveNow(values);
      // 서버가 거절할 미디어 북은 저장 요청에서 빠진다(`formToServer`). 그때 "임시저장했어요"만 말하면 미디어 북도
      // 저장된 줄 안다.
      if (mediaBookSchema.safeParse(values.mediaBook).success) toast.success("임시저장했어요.");
      else toast.warning("임시저장했어요. 미디어 북은 고칠 항목이 있어 이번에는 저장하지 않았어요.");
    } catch (error) {
      toast.error(storyAutosaveErrorMessage(error) ?? "임시저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  // `handleSubmit`이 넘겨주는 values는 resolver(storyBuilderSchema)를 이미 통과한 파싱 결과라
  // (default() 적용 포함) 여기서 다시 parse()할 필요가 없다.
  async function handlePublish(values: StoryBuilderFormValues) {
    setRejectionReason(undefined);
    const payload = formToServer(values);
    setIsPublishing(true);
    try {
      const savedDraft = await saveDraft(payload);
      const result = await publishMutation.mutateAsync({ id: savedDraft.id });
      void navigate({ to: "/content/$type/$id", params: { type: "story", id: result.contentId } });
    } catch (error) {
      const reason = getFilterRejectionReason(error);
      if (reason) {
        setRejectionReason(reason);
        return;
      }
      const missingFields = getMissingFields(error);
      if (missingFields) {
        for (const field of missingFields) {
          // 상황 노트 키는 서버가 어느 노트인지 알려 주지 않지만 폼에서 같은 조건을 다시 따져 그 칸을 짚을 수 있다.
          const noteLocation = locateSituationNotePublishError(field, values.startingSetups);
          if (noteLocation) {
            form.setError(noteLocation.path, { type: "server", message: noteLocation.message });
            continue;
          }
          const formPath = STORY_MISSING_FIELD_FORM_PATH[field];
          if (formPath) form.setError(formPath, { type: "server", message: "필수 항목이에요." });
        }
        // setError는 formState.errors를 동기로 갱신한다 — 위 루프 직후 바로 읽어도 최신값이다.
        revealAndFocusFirstError(form.formState.errors);
        toast.error(missingFieldsMessage(missingFields, STORY_MISSING_FIELD_LABELS));
        return;
      }
      // 발행 전 초안 저장이 지워진 스탯을 쓰는 엔딩 조건으로 거절된 경우. 일반 실패 문구로 끝내면 작가는 다시 눌러 볼 뿐이라,
      // 자동저장과 같은 원인 문구를 보이고 발행 400 의 같은 원인(`endings.statRules`)과 같은 자리로 엔딩 탭을 연다.
      if (isEndingRuleStatNotFoundError(error)) {
        const formPath = STORY_MISSING_FIELD_FORM_PATH["endings.statRules"];
        if (formPath) form.setError(formPath, { type: "server", message: ENDING_RULE_STAT_NOT_FOUND_MESSAGE });
        revealAndFocusFirstError(form.formState.errors);
        toast.error(ENDING_RULE_STAT_NOT_FOUND_MESSAGE);
        return;
      }
      // 같은 원인이 상황 노트 조건에 있으면 서버가 조건 줄의 경로를 알려 준다 — 그 줄의 스탯 칸으로 바로 보낸다. 경로를 못 읽으면
      // 첫 시작설정의 상황 노트 목록으로 탭만 옮긴다.
      const noteRulePaths = situationNoteStatNotFoundPaths(error);
      if (noteRulePaths) {
        const paths = noteRulePaths.length > 0 ? noteRulePaths : ["startingSetups.0.situationNotes" as const];
        for (const path of paths) form.setError(path, { type: "server", message: SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE });
        revealAndFocusFirstError(form.formState.errors);
        toast.error(SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE);
        return;
      }
      if (isMediaBookPositionTakenError(error)) {
        toast.error(MEDIA_BOOK_POSITION_TAKEN_MESSAGE);
        return;
      }
      const mediaBookFailure = mediaBookPublishErrorMessage(error, values.mediaBook);
      if (mediaBookFailure) {
        setActiveTab("mediaBook");
        toast.error(mediaBookFailure);
        return;
      }
      const publishFailure = getPublishFailureMessage(error);
      if (publishFailure) {
        toast.error(publishFailure);
        return;
      }
      toast.error("발행에 실패했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsPublishing(false);
    }
  }

  // zodResolver 검증 실패(폼 스키마 위반) 경로. 먼저 걸리는 쪽이 덜
  // 친절할 이유가 없어 여기서도 토스트를 띄운다. 문구는 서버 400 경로와 같은 파일이 소유하되
  // 문장이 갈린다 — 이 경로에는 누락뿐 아니라 `.max(4)` 위반도
  // 온다.
  // `form.formState.errors` 가 아니라 인자로 받은 `errors` 를 쓴다 — 검증이 오류 객체를 새것으로 바꾼 직후라 폼 상태
  // 쪽은 아직 이전 객체다.
  function handlePublishInvalid(errors: FieldErrors<StoryBuilderFormValues>) {
    revealAndFocusFirstError(errors);
    toast.error(
      invalidFieldsMessage(
        flattenFieldErrorPaths(errors)
          .map(collapseMediaBookPath)
          .map(collapseStartingSetupListPath),
        {
          ...MISSING_FIELD_LABEL_BY_FORM_PATH,
          ...STORY_STARTING_SETUP_LIST_LABELS,
          [MEDIA_BOOK_PATH]: MEDIA_BOOK_LABEL,
          // 서버는 이 칸을 누락 필드로 보내지 않아(형식이 틀리면 요청 단계에서 거절한다) 위 서버 맵에 자리가 없다.
          "storySetting.defaultUserName": STORY_FIELD_LABELS["storySetting.defaultUserName"].label,
        },
      ),
    );
  }

  // 폼과 프리뷰가 동시에 살아 있어야 하므로(lg 이상 2단) 더 이상
  // isPreviewOpen으로 렌더 트리 자체를 분기하지 않는다. 매 렌더 같은 트리 위치(BuilderLayout의
  // preview 슬롯)에 같은 노드를 그려 넣어 React가 리마운트하지 않게 하고, lg 미만에서 그 노드를
  // 화면에 보일지는 BuilderLayout이 CSS로만 정한다(전체화면 토글). 미디어 북 탭에서는 그 열에 배치표가
  // 서는데, 대화 노드는 그때도 같은 자리(아래 슬롯의 첫 자식)에 숨겨 둔 채 남겨 대화·입력·스트림이 이어진다.
  //
  // `kind`는 활성 탭에서 파생한다(TABS[].preview). `TABS.find`가
  // undefined를 돌려줄 수 있는 건 타입상 뿐이다 — activeTab의 타입(StoryBuilderTab)이 TABS에서
  // 도출되므로 항상 매치가 있다. 그래도 타입 체커를 만족시킬 기본값이 필요해 "card"를 쓴다 — 초기
  // 활성 탭("profile")의 preview 값과 같고, 프리뷰 세션을 지연 시작하는 것과 같은 이유로 도달할 리 없는 분기에서
  // 프리뷰 세션을 만드는 "chat"보다 안전하다.
  const activeTabConfig = TABS.find((tab) => tab.id === activeTab);
  const previewNode = renderPreview({
    kind: activeTabConfig?.preview ?? "card",
    getPayload: () => formToServer(form.getValues()),
    // 대화 미리보기 첫 메시지 그림. 크기는 폼 값에 없으면(이 기기에서 방금 올린 그림) 최근 저장 응답에서 찾는다.
    getMediaBookImages: () =>
      toMediaBookPreviewImages(
        form.getValues("mediaBook.cells"),
        mediaBookThumbnails.resolveUrl,
        new Map(
          (draft.mediaBook?.cells ?? []).map((cell) => [
            cell.imageAssetId,
            { width: cell.imageWidth ?? undefined, height: cell.imageHeight ?? undefined },
          ]),
        ),
      ),
    onClose: () => setIsPreviewOpen(false),
    thumbnailUrl,
  });

  // 발행 시도가 실패하면 누락 필드를 담은 탭 라벨을 에러 상태로 표시한다.
  const errorTabIds = errorTabs(form.formState.errors, TABS);

  return (
    <FormProvider {...form}>
      {/* 빌더는 전역 Header 대신 이 전용 상단바를 쓴다(같은
          56px 자리, `routes/__root.tsx`가 `/builder` 경로에서 Header를 뺀다). 저장 계약("자동저장")을
          여기서 한 번 말해 둔다 — 안 그러면 사용자가 그 단어를 처음 만나는 자리가 빨간 실패
          토스트다. */}
      <BuilderTopBar
        title="스토리 만들기"
        autosaveNotice="변경사항은 자동으로 저장돼요."
        actions={
          <BuilderTopBarActions
            guidePath={creationGuidePath("story", activeTab)}
            isPublishing={isPublishing}
            isPreviewOpen={isPreviewOpen}
            // 미디어 북 탭에서는 이 버튼이 여는 화면이 배치표라 그 화면의 머리와 같은 이름을 단다.
            previewLabel={activeTab === "mediaBook" ? "배치표" : undefined}
            previewIcon={activeTab === "mediaBook" ? <Grid3x3 aria-hidden className="size-3.5" /> : undefined}
            onPreview={() => setIsPreviewOpen((prev) => !prev)}
            onSaveNow={() => void handleSaveNow()}
            onPublish={() => void form.handleSubmit(handlePublish, handlePublishInvalid)()}
          />
        }
      />
      {/* 화면 상태는 탭과 미리보기 열(미디어 북 배치표) 양쪽이 읽을 수 있게 둘을 함께 감싼다. */}
      <BuilderUiStateContext.Provider value={uiState}>
        {/* 미디어 북 칸 썸네일 주소는 탭을 옮겨도 남아야 해서(방금 올린 파일의 로컬 주소) 탭 바깥에서 붙잡는다. */}
        <MediaBookThumbnailsProvider value={mediaBookThumbnails}>
          {/* 미디어 북의 고른 칸도 탭을 옮겨도 남아야 해 탭 바깥에 둔다. 셸 상태가 아닌 것은 칸을 고를 때마다 셸과 미리보기가 다시 그려지지 않게 하려는 것이다. */}
          <MediaBookSelectionProvider setPreviewOpen={setIsPreviewOpen}>
            <BuilderLayout
              isPreviewOpen={isPreviewOpen}
              preview={
                // 대화 노드는 언제나 첫 자식 자리에 있어 탭을 바꿔도 리마운트되지 않는다(래퍼를 조건부로 그리면 대화가
                // 사라진다). 배치표는 둘째 자리에 미디어 북 탭일 때만 그려, 숨은 칸 버튼이 다른 탭에 남지 않는다.
                <>
                  <div className={activeTab === "mediaBook" ? "hidden" : undefined}>{previewNode}</div>
                  {activeTab === "mediaBook" && <MediaBookGridPane onClose={() => setIsPreviewOpen(false)} />}
                </>
              }
            >
              {rejectionReason !== undefined && draftId !== undefined && (
                <div role="alert" className="flex items-start justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-destructive-text">발행이 거부되었어요</p>
                    <p className="mt-1 text-sm text-muted-foreground">{rejectionReason}</p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() =>
                      void AppealModal.call({ target: { kind: "publish-rejection", rejectionId: draftId } })
                    }
                  >
                    이의제기
                  </Button>
                </div>
              )}

              {/* lg 이상에서는 탭 목록과 첫 내용 사이를 각 탭 본문 컴포넌트 루트의 윗여백(`py-6`, 24px) 하나로 둔다 — `Tabs` 기본 간격까지 더하면
                  상단바 → 탭 목록(24px)보다 벌어진다. lg 미만은 그대로다. */}
              <Tabs
                value={activeTab}
                onValueChange={(value) => isStoryBuilderTab(value) && setActiveTab(value)}
                className="lg:gap-0"
              >
                <BuilderTabStrip tabs={TABS} errorTabIds={errorTabIds} />

                <TabsContent value="profile">
                  <ProfileTab
                    thumbnailUrl={thumbnailUrl}
                    onUploadComplete={profileImageLocal.rememberUploadedFile}
                    onPick={profileImageLocal.rememberPickedImage}
                  />
                </TabsContent>
                <TabsContent value="setting">
                  <SettingTab />
                </TabsContent>
                <TabsContent value="startingSetup">
                  <StartingSetupTab />
                </TabsContent>
                <TabsContent value="stat">
                  <StatTab />
                </TabsContent>
                <TabsContent value="situationNote">
                  <SituationNoteTab />
                </TabsContent>
                <TabsContent value="mediaBook">
                  <MediaBookTab />
                </TabsContent>
                <TabsContent value="keywordNote">
                  <KeywordNoteTab />
                </TabsContent>
                <TabsContent value="shortcut">
                  <ShortcutTab />
                </TabsContent>
                <TabsContent value="ending">
                  <EndingTab />
                </TabsContent>
                <TabsContent value="registration">
                  <RegistrationTab />
                </TabsContent>
              </Tabs>
            </BuilderLayout>
          </MediaBookSelectionProvider>
        </MediaBookThumbnailsProvider>
      </BuilderUiStateContext.Provider>
    </FormProvider>
  );
}

/** `Tabs`의 `onValueChange`가 주는 값이 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓰고 화면이 실제로
 * 그리는 `TABS`를 근거로 삼는다 — 탭을 추가해도 술어가 자동으로 따라온다. */
function isStoryBuilderTab(value: string): value is StoryBuilderTab {
  return TABS.some((tab) => tab.id === value);
}

/** 미디어 북 오류 경로를 `mediaBook` 하나로 접는다(이유는 `MEDIA_BOOK_PATH` 주석). */
function collapseMediaBookPath(path: string): string {
  return path === MEDIA_BOOK_PATH || path.startsWith(`${MEDIA_BOOK_PATH}.`) || path.startsWith(`${MEDIA_BOOK_PATH}[`)
    ? MEDIA_BOOK_PATH
    : path;
}
