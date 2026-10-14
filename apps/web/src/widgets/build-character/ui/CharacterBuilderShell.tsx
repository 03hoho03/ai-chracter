import { useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent } from "@ai-character-chat/ui/components/tabs";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { FormProvider, useForm, useWatch, type FieldErrors, type Resolver } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, type CharacterDraftContent } from "@/entities/content";
import type { PreviewStartPayload } from "@/entities/preview-session";
import {
  characterBuilderSchema,
  characterMissingFieldFormPath,
  characterSaveErrorMessage,
  formToServer,
  serverToForm,
  CHARACTER_COLLAPSIBLE_LISTS,
  CHARACTER_FIELD_LABELS,
  CHARACTER_TABS,
  type CharacterBuilderFormValues,
  type CharacterBuilderTab,
} from "@/features/build-character";
import {
  BuilderLayout,
  BuilderTabStrip,
  BuilderUiStateContext,
  BuilderTopBar,
  BuilderTopBarActions,
  errorItemKeys,
  errorsAtPaths,
  errorTabs,
  fieldLabelForPath,
  FirstPublishConfirmModal,
  firstErrorLocation,
  flattenFieldErrorPaths,
  getFilterRejectionReason,
  getMissingFields,
  getPublishFailureMessage,
  missingFieldsMessage,
  PUBLISH_ISSUES_TOAST,
  PublishIssueList,
  publishIssueRows,
  resolveProfileImageUrl,
  tabFromSearch,
  tabToSearch,
  useAutosave,
  useConfirmFirstPublish,
  useCreateBuilderUiState,
  useDraftPersistence,
  useFocusFirstError,
  useProfileImageLocalUrl,
  usePublishChecklist,
} from "@/features/build-common";
import { AppealModal } from "@/features/submit-appeal";
import { creationGuidePath } from "@/shared/config/creationGuide";

import { CHARACTER_REQUIRED_TAB_IDS } from "../model/requiredTabs";
import { VISIBILITY_LABELS } from "../model/visibilityLabels";
import { AdvancedTab } from "./AdvancedTab";
import { DetailTab } from "./DetailTab";
import { IntroTab } from "./IntroTab";
import { ProfileTab } from "./ProfileTab";
import { PromptTab } from "./PromptTab";

type CharacterBuilderShellProps = {
  draft: CharacterDraftContent;
  draftId: string | undefined;
  /** 주소의 `?tab=` 값 — 처음 열 탭을 고른다. 이 빌더에 없는 탭 id 면 기본 탭이다. */
  tab: string | undefined;
  /** 탭을 바꿀 때 주소에 적을 값(기본 탭이면 `undefined`). */
  onTabChange: (tab: string | undefined) => void;
  renderPreview: (args: {
    kind: "card" | "chat";
    getPayload: () => PreviewStartPayload;
    onClose: () => void;
    thumbnailUrl: string | null;
  }) => ReactNode;
};

// 탭 목록은 features/build-character/model/tabs.ts(CHARACTER_TABS)가 단일 소스다 —
// fields(에러 탭 매칭용 경로 프리픽스)·preview가 이 배열에 함께 실려 있다.
const TABS = CHARACTER_TABS;

/** 5탭 단일 useForm 셸. 자동저장/발행/
 * 미리보기를 여기서 연동한다.
 *
 * `draftId`는 아직 서버에 없는 초안이면 undefined다 — 첫 저장이 초안을 만들고 URL을 바꾼다. */
export function CharacterBuilderShell({ draft, draftId, tab, onTabChange, renderPreview }: CharacterBuilderShellProps) {
  const navigate = useNavigate();
  const confirmFirstPublish = useConfirmFirstPublish();
  const [activeTab, setActiveTabState] = useState<CharacterBuilderTab>(() => tabFromSearch(tab, TABS));
  // 탭을 바꾸는 모든 길(탭 줄·첫 오류로 이동·빈 상태 안내)이 여기를 지나 주소의 `?tab=` 도 함께 바꾼다 — 새로고침하면 보던
  // 탭으로 돌아온다. 화면은 로컬 상태로 바로 바꾸고 주소는 뒤따른다(주소 이동을 기다리면 탭 전환이 한 박자 늦다).
  function setActiveTab(nextTab: CharacterBuilderTab) {
    setActiveTabState(nextTab);
    onTabChange(tabToSearch(nextTab, TABS));
  }
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  // 폼 컨벤션(중복 제출 방지는 `isSubmitting`)에서 의도적으로 벗어난다 — `form.formState.isSubmitting`은
  // 검증 구간까지 포함해 true가 되는데 발행 버튼은 네이티브 `disabled`라 유효성 실패 때마다 포커스가
  // body로 떨어진다. onValid 경로(handlePublish)에서만 켜지는 로컬 state로 대신한다.
  const [isPublishing, setIsPublishing] = useState(false);
  const [rejectionReason, setRejectionReason] = useState<string>();
  // 반복 항목의 열림 여부. 탭 본문은 탭을 바꿀 때 언마운트되므로 탭을 오가도 펼쳐 둔 항목이 남도록 셸이 쥔다.
  const uiState = useCreateBuilderUiState();
  // mode/reValidateMode/shouldUnregister를 명시하지 않는다 — RHF 기본값(제출 전엔 조용히, 제출 후엔
  // onChange 재검증)이 "발행 시도 전에는 오류를 띄우지 않는다"는 요구와 같다. 다만 기본 재검증은 입력한 칸 이름의 오류만
  // 고치므로, 다른 칸에 걸린 오류와 `setValue` 로 쓰는 칸의 오류는 아래 `usePublishChecklist` 가 발행 시도 뒤 통째로 갈아 끼운다.
  const form = useForm<CharacterBuilderFormValues>({
    // intro.exampleDialogues/situationalImages 등 `.default()`가 붙은 필드는 zod의 input 타입과
    // output 타입이 갈린다 — zodResolver()는 `Resolver<Input, any, Output>`을 돌려주는데
    // useForm<CharacterBuilderFormValues>(output 하나로 폼 전체를 표현)는 `Resolver<Output, any,
    // Output>`을 요구해 타입이 어긋난다. RHF는 세 번째 제네릭(TTransformedValues)으로 이 간극을
    // 메우도록 설계돼 있지만, 그러면 `getValues()`/`formToServer` 전체가 매 defaultable 필드마다
    // 옵셔널 타입으로 번진다(자동저장·미리보기 경로까지). 런타임에는 안전하다 — defaultValues
    // (serverToForm)가 이 필드들을 항상 채워 넘기고 이후 어떤 입력도 그걸 undefined로 되돌리지 않는다.
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions -- 위 사유(zod .default()/RHF Resolver 제네릭의 구조적 한계)
    resolver: zodResolver(characterBuilderSchema) as Resolver<CharacterBuilderFormValues>,
    defaultValues: serverToForm(draft),
    // 첫 오류로 가는 포커스는 `useFocusFirstError` 가 확인 목록이 선 뒤에 준다. RHF 가 검증 직후 먼저 포커스하면 목록이 서기 전
    // 자리로 스크롤돼 그 칸이 목록에 밀려 화면 밖에 남는다.
    shouldFocusError: false,
  });

  // 대표 이미지 칸과 미리보기 카드가 같은 그림, 곧 폼이 지금 가진 그림을 보이도록 표시 주소를 여기서 한 번 정해
  // 둘에 내려 준다. 초안 응답의 주소는 마지막 저장이 본 그림일 뿐이라 그대로 쓰면 저장이 끝날 때까지 카드가 옛
  // 그림에 머문다. 방금 올리거나 고른 그림의 주소를 탭이 아니라 셸이 쥐는 이유는 탭을 옮기면 탭 본문이
  // 언마운트되기 때문이다. 셸은 폼 값 변화를 구독하지 않으므로(자동저장의 `form.watch` 콜백 구독은 재렌더를
  // 일으키지 않는다) 이 필드만 따로 구독한다.
  const profileImage = useWatch({ control: form.control, name: "profile.image" });
  const profileImageLocal = useProfileImageLocalUrl();
  const thumbnailUrl = resolveProfileImageUrl({ image: profileImage, local: profileImageLocal.local, draft });

  const { saveDraft, saveStatus } = useDraftPersistence({ type: "character", draftId, initialNovelPermission: draft.novelPermission });
  const publishMutation = usePublishContentMutation();

  // 발행 실패 시 첫 에러 필드로 이동한다(탭이 다르면 먼저 전환). tabId는
  // firstErrorLocation이 TABS 근거로 돌려주는 값이라 항상 유효하지만, 타입은 string이라 좁힘이
  // 필요하다(`as` 대신 술어 — isCharacterBuilderTab, 파일 하단).
  const focusFirstError = useFocusFirstError({
    form,
    activeTab,
    setActiveTab: (tabId) => {
      if (isCharacterBuilderTab(tabId)) setActiveTab(tabId);
    },
  });

  // 탭 줄의 채움 표시, 발행을 누른 뒤 고친 칸의 오류 해제, 남은 서버 거절을 셸 한 곳에서 맞춘다.
  const checklist = usePublishChecklist({
    form,
    schema: characterBuilderSchema,
    tabs: TABS,
    requiredTabIds: CHARACTER_REQUIRED_TAB_IDS,
  });

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      // `watch` 콜백이 주는 값은 `DeepPartial`이다(미등록 필드가 있을 수 있어서). 구독은 **변경
      // 신호**로만 쓰고 값은 `getValues()`로 읽는다 — 단언 없이 완전한 폼 타입이 나온다.
      const subscription = form.watch(() => cb(form.getValues()));
      return () => subscription.unsubscribe();
    },
    formToServer,
    save: saveDraft,
    onSchedule: saveStatus.markPending,
    flushOnUnmount: () => draftId !== undefined,
    errorMessage: characterSaveErrorMessage,
  });

  /** 상황별 이미지 등록(`POST /assets/{id}/register-situational-image`)은 content_version_id를
   * 요구한다 — 초안이 아직 없으면 여기서 지금 폼 값으로 만들고, 이미 있으면 방금 입력한
   * 노출 상황까지 저장한 뒤 진행한다. `type` 검사는 판별 유니언을 좁히기 위한 것이다. */
  async function ensureContentVersionId(): Promise<string> {
    const savedDraft = await saveDraft(formToServer(form.getValues()));
    if (savedDraft.type !== "character") throw new Error("캐릭터 초안이 아니에요.");
    return savedDraft.contentVersionId;
  }

  async function handleSaveNow() {
    try {
      await saveNow(form.getValues());
      toast.success("임시저장했어요.");
    } catch (error) {
      toast.error(characterSaveErrorMessage(error) ?? "임시저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  // `handleSubmit`이 넘겨주는 values는 resolver(characterBuilderSchema)를 이미 통과한 파싱 결과라
  // (default() 적용 포함) 여기서 다시 parse()할 필요가 없다.
  async function handlePublish(values: CharacterBuilderFormValues) {
    setRejectionReason(undefined);
    // 검사가 오류 객체를 통째로 바꿔 지난 서버 거절도 지워졌다. 확인 모달에서 취소하면 그대로 돌아와야 하므로 다시 건다.
    checklist.reapplyServerIssues();
    const { visibility } = values.registration;
    const shouldPublish = await confirmFirstPublish({
      contentId: draftId,
      contentLabel: "캐릭터",
      visibility,
      visibilityLabel: VISIBILITY_LABELS[visibility],
    });
    if (!shouldPublish) return;
    // 이제 실제로 보내니 지난 서버 거절은 이번 발행 응답이 새로 정한다.
    checklist.setServerIssues([]);
    const payload = formToServer(values);
    setIsPublishing(true);
    try {
      const savedDraft = await saveDraft(payload);
      const result = await publishMutation.mutateAsync({ id: savedDraft.id });
      void navigate({ to: "/content/$type/$id", params: { type: "character", id: result.contentId } });
    } catch (error) {
      const reason = getFilterRejectionReason(error);
      if (reason) {
        setRejectionReason(reason);
        return;
      }
      const missingFields = getMissingFields(error);
      if (missingFields) {
        const unknownFields = missingFields.filter((field) => characterMissingFieldFormPath(field) === undefined);
        checklist.setServerIssues(
          missingFields.flatMap((field) => {
            const path = characterMissingFieldFormPath(field);
            return path === undefined ? [] : [{ path, message: "필수 항목이에요." }];
          }),
        );
        // setError는 formState.errors를 동기로 갱신한다 — 위 호출 직후 바로 읽어도 최신값이다.
        // 서버는 목록 전체(상황별 이미지)만 가리켜 여기서 열릴 항목은 보통 없지만, 클라 검증 경로와 같은 순서를 지킨다.
        revealAndFocus(form.formState.errors);
        // 빌더가 모르는 키는 칸에 걸 수 없어 목록에 오르지 않는다 — 그때만 토스트가 직접 말한다.
        toast.error(unknownFields.length > 0 ? missingFieldsMessage(unknownFields, {}) : PUBLISH_ISSUES_TOAST);
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

  // 오류를 품은 접힌 항목을 연다. 첫 오류로 포커스를 옮기기 전에 불러야 그 필드가 보이는 상태에서 포커스가 간다. 렌더에서
  // 오류로 파생하지 않고 열림으로 기록하는 이유는, 발행 뒤에는 고치는 입력마다 다시 검증돼 오류가 풀리는 순간 항목이 접히며
  // 입력 중이던 칸의 포커스를 잃기 때문이다. 값 id 는 지금 폼 값에서 읽는다 — 오류는 방금 이 값으로 검증해 만든 것이라 오류 경로의
  // 인덱스가 지금 배열의 같은 자리를 가리킨다.
  function revealAndFocus(errors: FieldErrors<CharacterBuilderFormValues>) {
    uiState.open(errorItemKeys(errors, form.getValues(), CHARACTER_COLLAPSIBLE_LISTS, TABS));
    focusFirstError(firstErrorLocation(errors, TABS));
  }

  // zodResolver 검증 실패(폼 스키마 위반) 경로. 서버 400 과 같은 토스트로 폼 열 맨 위 목록을 가리킨다. 검사가 오류 객체를
  // 통째로 바꿔 지난 서버 거절이 지워졌으므로 아직 유효한 것을 다시 걸고, 첫 오류는 둘을 합쳐 고른다.
  function handlePublishInvalid(errors: FieldErrors<CharacterBuilderFormValues>) {
    const serverPaths = checklist.reapplyServerIssues();
    revealAndFocus(errorsAtPaths([...flattenFieldErrorPaths(errors), ...serverPaths]));
    toast.error(PUBLISH_ISSUES_TOAST);
  }

  // 폼과 프리뷰가 동시에 살아 있어야 하므로(lg 이상 2단) 더 이상
  // isPreviewOpen으로 렌더 트리 자체를 분기하지 않는다. 매 렌더 같은 트리 위치(BuilderLayout의
  // preview 슬롯)에 같은 노드를 그려 넣어 React가 리마운트하지 않게 하고, lg 미만에서 그 노드를
  // 화면에 보일지는 BuilderLayout이 CSS로만 정한다(전체화면 토글).
  //
  // `kind`는 활성 탭에서 파생한다(TABS[].preview). `TABS.find`가
  // undefined를 돌려줄 수 있는 건 타입상 뿐이다 — activeTab의 타입(CharacterBuilderTab)이 TABS에서
  // 도출되므로 항상 매치가 있다. 그래도 타입 체커를 만족시킬 기본값이 필요해 "card"를 쓴다 — 초기
  // 활성 탭("profile")의 preview 값과 같고, 프리뷰 세션을 지연 시작하는 것과 같은 이유로 도달할 리 없는 분기에서
  // 프리뷰 세션을 만드는 "chat"보다 안전하다.
  const activeTabConfig = TABS.find((tab) => tab.id === activeTab);
  const previewNode = renderPreview({
    kind: activeTabConfig?.preview ?? "card",
    getPayload: () => formToServer(form.getValues()),
    onClose: () => setIsPreviewOpen(false),
    thumbnailUrl,
  });

  // 발행 시도가 실패하면 누락 필드를 담은 탭 라벨을 에러 상태로 표시하고, 폼 열 맨 위에 남은 항목을 나열한다.
  // 목록은 발행을 누른 뒤에만 그린다 — 칸 하나를 떠날 때 거는 검사(스탯 범위)도 오류 객체에 들어가지만, 그건 그 칸의 안내이지
  // 발행이 막혔다는 말이 아니다.
  const errorTabIds = errorTabs(form.formState.errors, TABS);
  const issueRows = publishIssueRows(
    flattenFieldErrorPaths(form.formState.errors),
    TABS,
    (path) => checklist.serverLabel(path) ?? fieldLabelForPath(path, CHARACTER_FIELD_LABELS),
  );

  return (
    <FormProvider {...form}>
      <BuilderUiStateContext.Provider value={uiState}>
        {/* 빌더는 전역 Header 대신 이 전용 상단바를 쓴다(같은
            57px 자리, `routes/__root.tsx`가 `/builder` 경로에서 Header를 뺀다). 저장 계약("자동저장")을
            여기서 한 번 말해 둔다 — 안 그러면 사용자가 그 단어를 처음 만나는 자리가 빨간 실패
            토스트다. */}
        <BuilderTopBar
          title="캐릭터 만들기"
          autosaveNotice="변경사항은 자동으로 저장돼요."
          actions={
            <BuilderTopBarActions
              guidePath={creationGuidePath("character", activeTab)}
              isPublishing={isPublishing}
              isPreviewOpen={isPreviewOpen}
              saveStatus={saveStatus}
              onPreview={() => setIsPreviewOpen((prev) => !prev)}
              onSaveNow={() => void handleSaveNow()}
              onPublish={() => {
                checklist.markAttempted();
                void form.handleSubmit(handlePublish, handlePublishInvalid)();
              }}
            />
          }
        />
        <BuilderLayout isPreviewOpen={isPreviewOpen} preview={previewNode}>
          {checklist.hasAttempted && issueRows.length > 0 && (
            <PublishIssueList rows={issueRows} onSelect={(path) => revealAndFocus(errorsAtPaths([path]))} />
          )}
          {rejectionReason !== undefined && draftId !== undefined && (
            <div role="alert" className="flex items-start justify-between gap-3 rounded-lg bg-destructive/10 px-4 py-3">
              <div className="min-w-0 break-keep wrap-break-word">
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
            onValueChange={(value) => isCharacterBuilderTab(value) && setActiveTab(value)}
            className="lg:gap-0"
          >
            <BuilderTabStrip
              tabs={TABS}
              activeTab={activeTab}
              errorTabIds={errorTabIds}
              requiredTabIds={CHARACTER_REQUIRED_TAB_IDS}
              completedTabIds={checklist.completedTabIds}
            />

            <TabsContent value="profile">
              <ProfileTab
                thumbnailUrl={thumbnailUrl}
                onUploadComplete={profileImageLocal.rememberUploadedFile}
                onPick={profileImageLocal.rememberPickedImage}
              />
            </TabsContent>
            <TabsContent value="intro">
              <IntroTab />
            </TabsContent>
            <TabsContent value="prompt">
              <PromptTab />
            </TabsContent>
            <TabsContent value="advanced">
              <AdvancedTab ensureContentVersionId={ensureContentVersionId} savedImages={draft.situationalImages} />
            </TabsContent>
            <TabsContent value="detail">
              <DetailTab />
            </TabsContent>
          </Tabs>
        </BuilderLayout>
        <FirstPublishConfirmModal />
      </BuilderUiStateContext.Provider>
    </FormProvider>
  );
}

/** `Tabs`의 `onValueChange`가 주는 값이 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓰고 화면이 실제로
 * 그리는 `TABS`를 근거로 삼는다 — 탭을 추가해도 술어가 자동으로 따라온다. */
function isCharacterBuilderTab(value: string): value is CharacterBuilderTab {
  return TABS.some((tab) => tab.id === value);
}
