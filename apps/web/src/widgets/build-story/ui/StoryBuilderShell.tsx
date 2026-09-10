import { useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { TriangleAlert } from "lucide-react";
import { FormProvider, useForm, type FieldErrors, type Path, type Resolver } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, type StoryDraftContent } from "@/entities/content";
import type { PreviewStartPayload } from "@/entities/preview-session";
import {
  storyBuilderSchema,
  formToServer,
  serverToForm,
  STORY_TABS,
  type StoryBuilderFormValues,
  type StoryBuilderTab,
} from "@/features/build-story";
import { useAutosave, useDraftPersistence } from "@/features/build-common";
import { AppealModal } from "@/features/submit-appeal";
import { isApiError } from "@/shared/lib/api/client";
import {
  BuilderLayout,
  errorTabs,
  firstErrorLocation,
  useFocusFirstError,
  useHorizontalScrollClip,
} from "@/widgets/build-common";

import { storyBuilderActiveTabAtom } from "../model/activeTabAtom";
import { EndingTab } from "./EndingTab";
import { KeywordNoteTab } from "./KeywordNoteTab";
import { ProfileTab } from "./ProfileTab";
import { RegistrationTab } from "./RegistrationTab";
import { SettingTab } from "./SettingTab";
import { ShortcutTab } from "./ShortcutTab";
import { StartingSetupTab } from "./StartingSetupTab";
import { StatTab } from "./StatTab";

// 탭 목록은 features/build-story/model/tabs.ts(STORY_TABS)가 단일 소스다(builder-techspec.md §4-1) —
// fields(에러 탭 매칭용 경로 프리픽스)·preview(D-2)가 이 배열에 함께 실려 있다.
const TABS = STORY_TABS;

// storyBuilderSchema의 profile.image/registration.genre/target은 초안 상태를 표현하기 위해
// nullable이라(US-092/095), zodResolver 검증을 통과해도 서버(validate_story_publish)가 요구하는
// 값이 비어 있을 수 있다(CharacterBuilderShell.tsx와 동일한 간극 — customPrompt/settingText/
// startingSetups/description 등 나머지 필드는 이미 폼 스키마가 min(1)/min(10)으로 막아 이 경로에
// 도달하지 않는다) — 그 필드명을 한국어 라벨로 보여준다.
const MISSING_FIELD_LABELS: Record<string, string> = {
  name: "이름",
  oneLiner: "한줄소개",
  thumbnailAssetId: "대표 이미지",
  description: "등록 설명",
  genreId: "장르",
  target: "타겟",
};

// 위 서버 필드명을 form.setError()가 받는 폼 경로로 옮긴다(builder-goal-prompt.md §5-2) — 키 집합은
// MISSING_FIELD_LABELS와 같고, 값은 features/build-story/model/tabs.ts(STORY_TABS)의 fields 프리픽스
// 아래에 들어간다(profile.*는 profile 탭, registration.*는 registration 탭).
const MISSING_FIELD_FORM_PATH: Partial<Record<string, Path<StoryBuilderFormValues>>> = {
  name: "profile.name",
  oneLiner: "profile.oneLiner",
  thumbnailAssetId: "profile.image",
  description: "registration.description",
  genreId: "registration.genre",
  target: "registration.target",
};

type StoryBuilderShellProps = {
  draft: StoryDraftContent;
  draftId: string | null;
  renderPreview: (args: {
    kind: "card" | "chat";
    getPayload: () => PreviewStartPayload;
    onClose: () => void;
  }) => ReactNode;
};

/** techspec-builder-story.md §0/§1 — 8탭 단일 useForm 셸. 자동저장(US-096)/발행(US-085)/
 * 미리보기(US-088)를 CharacterBuilderShell.tsx(US-105)와 동일한 방식으로 연동한다.
 *
 * `draftId`는 아직 서버에 없는 초안이면 null이다(US-007) — 첫 저장이 초안을 만들고 URL을 바꾼다. */
export function StoryBuilderShell({ draft, draftId, renderPreview }: StoryBuilderShellProps) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useAtom(storyBuilderActiveTabAtom);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [rejectionReason, setRejectionReason] = useState<string | null>(null);
  // mode/reValidateMode/shouldUnregister를 명시하지 않는다 — RHF 기본값(제출 전엔 조용히, 제출 후엔
  // onChange 재검증)이 이미 "발행 시도 후에는 고치는 즉시 에러가 풀린다"는 요구(D-10)와 정확히 같다
  // (builder-goal-prompt.md §5-3). 기본값을 그대로 두는 것 자체가 이 단계의 결정이다.
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

  const { saveDraft } = useDraftPersistence({ type: "story", draftId });
  const publishMutation = usePublishContentMutation();

  // builder-techspec.md §9-1 — 발행 실패 시 첫 에러 필드로 이동한다(탭이 다르면 먼저 전환). tabId는
  // firstErrorLocation이 TABS 근거로 돌려주는 값이라 항상 유효하지만, 타입은 string이라 좁힘이
  // 필요하다(`as` 대신 술어 — isStoryBuilderTab, 파일 하단).
  const focusFirstError = useFocusFirstError({
    form,
    activeTab,
    setActiveTab: (tabId) => {
      if (isStoryBuilderTab(tabId)) setActiveTab(tabId);
    },
  });

  // 스텝 탭 스트립 가로 스크롤 신호(P2) — `useHorizontalScrollClip` 참고.
  const tabsScroll = useHorizontalScrollClip();

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      // `watch` 콜백이 주는 값은 `DeepPartial`이다(미등록 필드가 있을 수 있어서). 구독은 **변경
      // 신호**로만 쓰고 값은 `getValues()`로 읽는다 — 단언 없이 완전한 폼 타입이 나온다.
      const subscription = form.watch(() => cb(form.getValues()));
      return () => subscription.unsubscribe();
    },
    formToServer,
    save: saveDraft,
    flushOnUnmount: () => draftId !== null,
  });

  async function handleSaveNow() {
    try {
      await saveNow(form.getValues());
      toast.success("임시저장했어요.");
    } catch {
      toast.error("임시저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  // `handleSubmit`이 넘겨주는 values는 resolver(storyBuilderSchema)를 이미 통과한 파싱 결과라
  // (default() 적용 포함) 여기서 다시 parse()할 필요가 없다(builder-goal-prompt.md §5-2).
  async function handlePublish(values: StoryBuilderFormValues) {
    setRejectionReason(null);
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
          const formPath = MISSING_FIELD_FORM_PATH[field];
          if (formPath) form.setError(formPath, { type: "server", message: "필수 항목이에요." });
        }
        // setError는 formState.errors를 동기로 갱신한다 — 위 루프 직후 바로 읽어도 최신값이다.
        focusFirstError(firstErrorLocation(form.formState.errors, TABS));
        const missingLabels = missingFields.map((field) => MISSING_FIELD_LABELS[field] ?? field);
        toast.error(`발행하려면 다음 항목을 입력해주세요: ${missingLabels.join(", ")}`);
        return;
      }
      toast.error("발행에 실패했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsPublishing(false);
    }
  }

  // zodResolver 검증 실패(폼 스키마 위반) 경로 — builder-techspec.md §9-1.
  function handlePublishInvalid(errors: FieldErrors<StoryBuilderFormValues>) {
    focusFirstError(firstErrorLocation(errors, TABS));
  }

  // builder-techspec.md §4-3/§6 — 폼과 프리뷰가 동시에 살아 있어야 하므로(D-1의 lg 이상 2단) 더 이상
  // isPreviewOpen으로 렌더 트리 자체를 분기하지 않는다. 매 렌더 같은 트리 위치(BuilderLayout의
  // preview 슬롯)에 같은 노드를 그려 넣어 React가 리마운트하지 않게 하고, lg 미만에서 그 노드를
  // 화면에 보일지는 BuilderLayout이 CSS로만 정한다(전체화면 토글).
  //
  // builder-techspec.md §6-1 — `kind`는 활성 탭에서 파생한다(TABS[].preview). `TABS.find`가
  // undefined를 돌려줄 수 있는 건 타입상 뿐이다 — activeTab의 타입(StoryBuilderTab)이 TABS에서
  // 도출되므로 항상 매치가 있다. 그래도 타입 체커를 만족시킬 기본값이 필요해 "card"를 쓴다 — 초기
  // 활성 탭("profile")의 preview 값과 같고, D-7(지연 시작)과 같은 이유로 도달할 리 없는 분기에서
  // 프리뷰 세션을 만드는 "chat"보다 안전하다.
  const activeTabConfig = TABS.find((tab) => tab.id === activeTab);
  const previewNode = renderPreview({
    kind: activeTabConfig?.preview ?? "card",
    getPayload: () => formToServer(form.getValues()),
    onClose: () => setIsPreviewOpen(false),
  });

  // D-4(builder-goal-prompt.md §5-1) — 발행 시도가 실패하면 누락 필드를 담은 탭 라벨을 에러 상태로 표시한다.
  const errorTabIds = errorTabs(form.formState.errors, TABS);

  return (
    <FormProvider {...form}>
      <BuilderLayout isPreviewOpen={isPreviewOpen} preview={previewNode}>
        {/* 저장 계약을 한 번 말해 둔다 — 자동저장은 성공해도 아무 표시가 없어서, 이 문장이 없으면
            사용자가 "자동저장"이라는 단어를 처음 만나는 자리가 빨간 실패 토스트다(US-007). */}
        <header className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-4">
            <h1 className="text-2xl font-bold break-keep tracking-tight text-foreground">스토리 만들기</h1>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="lg:hidden"
                onClick={() => setIsPreviewOpen(true)}
              >
                미리보기
              </Button>
              <Button type="button" variant="outline" onClick={() => void handleSaveNow()}>
                임시저장
              </Button>
              <Button
                disabled={isPublishing}
                onClick={() => void form.handleSubmit(handlePublish, handlePublishInvalid)()}
              >
                {isPublishing ? "발행 중..." : "발행"}
              </Button>
            </div>
          </div>
          <p className="text-sm break-keep text-muted-foreground">
            변경사항은 자동으로 저장돼요.
          </p>
        </header>

        {rejectionReason !== null && draftId !== null && (
          <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
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

        <Tabs value={activeTab} onValueChange={(value) => isStoryBuilderTab(value) && setActiveTab(value)}>
          {/* P2 — `TabsList`는 `inline-flex w-fit`이고 `overflow-x-auto`가 없어(packages/ui/tabs.tsx는
              고치지 않는다, 호출부 처방) 8개 탭이 넘치면 이 스트립이 아니라 페이지 전체가 가로로
              밀렸다(390px 실측 428px). 스트립 자체를 스크롤 컨테이너로 감싼다 — `-m-1 p-1`은
              `overflow-x-auto`가 포커스 링을 클립하는 걸 상쇄한다(apps/web/CLAUDE.md "overflow-x-auto는
              focus 링을 네 방향 모두 클립한다"). 오른쪽 페이드는 실제로 잘렸을 때만(`isClippedRight`)
              뜬다 — iOS Safari 오버레이 스크롤바엔 상시 표시가 없어(`useHorizontalScrollClip` 주석,
              packages/ui의 `data-clipped-below`와 같은 이유) 신호가 따로 필요하다. */}
          <div className="relative">
            <div ref={tabsScroll.ref} className="-m-1 overflow-x-auto p-1">
              <TabsList variant="line">
                {TABS.map((tab) => {
                  const hasError = errorTabIds.has(tab.id);
                  return (
                    <TabsTrigger
                      key={tab.id}
                      value={tab.id}
                      className={
                        hasError
                          ? "text-destructive-text hover:text-destructive-text data-active:text-destructive-text dark:text-destructive-text dark:hover:text-destructive-text dark:data-active:text-destructive-text"
                          : undefined
                      }
                    >
                      {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
                      {tab.label}
                      {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
                    </TabsTrigger>
                  );
                })}
              </TabsList>
            </div>
            {tabsScroll.isClippedRight && (
              <div
                aria-hidden
                className="pointer-events-none absolute inset-y-1 right-1 w-8 bg-linear-to-l from-background"
              />
            )}
          </div>

          <TabsContent value="profile">
            <ProfileTab thumbnailUrl={draft.thumbnailUrl} />
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
    </FormProvider>
  );
}

/** `TabsTrigger`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓰고(TS-03) 화면이 실제로
 * 그리는 `TABS`를 근거로 삼는다 — 탭을 추가해도 술어가 자동으로 따라온다. */
function isStoryBuilderTab(value: string): value is StoryBuilderTab {
  return TABS.some((tab) => tab.id === value);
}

/** 400 응답 detail 중 `{missingFields}`(필수 항목 누락)와 `{reason}`(자동 필터 거부)를 구분한다
 * (techspec-backend-content.md §1.2/§1.3, CharacterBuilderShell.tsx와 동일 판별). */
function getFilterRejectionReason(error: unknown): string | null {
  const apiError = isApiError(error) ? error : null;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return null;
  if ("reason" in apiError.detail) return String(apiError.detail.reason);
  return null;
}

/** 서버 필드명 원문(예: `"thumbnailAssetId"`)을 돌려준다 — 토스트용 한국어 라벨(`MISSING_FIELD_LABELS`)
 * 과 `form.setError()`용 폼 경로(`MISSING_FIELD_FORM_PATH`) 둘 다 이 원문을 키로 찾는다. */
function getMissingFields(error: unknown): string[] | null {
  const apiError = isApiError(error) ? error : null;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return null;
  const fields = apiError.detail.missingFields;
  if (!Array.isArray(fields)) return null;
  return fields.map(String);
}
