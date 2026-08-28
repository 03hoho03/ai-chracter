import { useState, type ReactNode } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, type StoryDraftContent } from "@/entities/content";
import type { PreviewStartPayload } from "@/entities/preview-session";
import { storyBuilderSchema, formToServer, serverToForm, type StoryBuilderFormValues } from "@/features/build-story";
import { useAutosave, useDraftPersistence } from "@/features/build-common";
import { AppealModal } from "@/features/submit-appeal";

import { storyBuilderActiveTabAtom, type StoryBuilderTab } from "../model/activeTabAtom";
import { EndingTab } from "./EndingTab";
import { KeywordNoteTab } from "./KeywordNoteTab";
import { ProfileTab } from "./ProfileTab";
import { RegistrationTab } from "./RegistrationTab";
import { SettingTab } from "./SettingTab";
import { ShortcutTab } from "./ShortcutTab";
import { StartingSetupTab } from "./StartingSetupTab";
import { StatTab } from "./StatTab";

const TABS: { id: StoryBuilderTab; label: string }[] = [
  { id: "profile", label: "프로필" },
  { id: "setting", label: "설정" },
  { id: "startingSetup", label: "시작설정" },
  { id: "stat", label: "스탯" },
  { id: "keywordNote", label: "키워드북" },
  { id: "shortcut", label: "단축어" },
  { id: "ending", label: "엔딩" },
  { id: "registration", label: "등록" },
];

/** 400 응답 detail 중 `{missingFields}`(필수 항목 누락)와 `{reason}`(자동 필터 거부)를 구분한다
 * (techspec-backend-content.md §1.2/§1.3, CharacterBuilderShell.tsx와 동일 판별). */
function getFilterRejectionReason(error: unknown): string | null {
  const apiError = error as ApiError;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return null;
  if ("reason" in apiError.detail) return String(apiError.detail.reason);
  return null;
}

// storyBuilderSchema의 profile.image/registration.genre/target은 초안 상태를 표현하기 위해
// nullable이라(US-092/095), 발행 버튼의 safeParse 가드를 통과해도 서버(validate_story_publish)가
// 요구하는 값이 비어 있을 수 있다(CharacterBuilderShell.tsx와 동일한 간극 — customPrompt/settingText/
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

function getMissingFieldLabels(error: unknown): string[] | null {
  const apiError = error as ApiError;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return null;
  const fields = (apiError.detail as { missingFields?: unknown }).missingFields;
  if (!Array.isArray(fields)) return null;
  return fields.map((field) => MISSING_FIELD_LABELS[String(field)] ?? String(field));
}

type StoryBuilderShellProps = {
  draft: StoryDraftContent;
  draftId: string | null;
  renderPreview: (args: { getPayload: () => PreviewStartPayload; onClose: () => void }) => ReactNode;
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
  const form = useForm<StoryBuilderFormValues>({ defaultValues: serverToForm(draft) });
  const values = useWatch({ control: form.control });
  const canPublish = storyBuilderSchema.safeParse(values).success;

  const { saveDraft } = useDraftPersistence({ type: "story", draftId });
  const publishMutation = usePublishContentMutation();

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      const subscription = form.watch((formValues) => cb(formValues as StoryBuilderFormValues));
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

  async function handlePublish() {
    setRejectionReason(null);
    const payload = formToServer(storyBuilderSchema.parse(form.getValues()));
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
      const missingLabels = getMissingFieldLabels(error);
      if (missingLabels) {
        toast.error(`발행하려면 다음 항목을 입력해주세요: ${missingLabels.join(", ")}`);
        return;
      }
      toast.error("발행에 실패했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsPublishing(false);
    }
  }

  if (isPreviewOpen) {
    return renderPreview({
      getPayload: () => formToServer(form.getValues()),
      onClose: () => setIsPreviewOpen(false),
    });
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      {/* 저장 계약을 한 번 말해 둔다 — 자동저장은 성공해도 아무 표시가 없어서, 이 문장이 없으면
          사용자가 "자동저장"이라는 단어를 처음 만나는 자리가 빨간 실패 토스트다(US-007). */}
      <header className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-2xl font-bold break-keep tracking-tight text-foreground">스토리 만들기</h1>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => setIsPreviewOpen(true)}>
              미리보기
            </Button>
            <Button type="button" variant="outline" onClick={() => void handleSaveNow()}>
              임시저장
            </Button>
            <Button disabled={!canPublish || isPublishing} onClick={() => void handlePublish()}>
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

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as StoryBuilderTab)}>
        <TabsList variant="line">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="profile">
          <ProfileTab form={form} />
        </TabsContent>
        <TabsContent value="setting">
          <SettingTab form={form} />
        </TabsContent>
        <TabsContent value="startingSetup">
          <StartingSetupTab form={form} />
        </TabsContent>
        <TabsContent value="stat">
          <StatTab form={form} />
        </TabsContent>
        <TabsContent value="keywordNote">
          <KeywordNoteTab form={form} />
        </TabsContent>
        <TabsContent value="shortcut">
          <ShortcutTab form={form} />
        </TabsContent>
        <TabsContent value="ending">
          <EndingTab form={form} />
        </TabsContent>
        <TabsContent value="registration">
          <RegistrationTab form={form} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
