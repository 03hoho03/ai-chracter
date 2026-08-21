import { useState, type ReactNode } from "react";
import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, type CharacterDraftContent } from "@/entities/content";
import type { PreviewStartPayload } from "@/entities/preview-session";
import {
  characterBuilderSchema,
  formToServer,
  serverToForm,
  type CharacterBuilderFormValues,
} from "@/features/build-character";
import { useAutosave, useDraftPersistence } from "@/features/build-common";
import { AppealModal } from "@/features/submit-appeal";

import { characterBuilderActiveTabAtom, type CharacterBuilderTab } from "../model/activeTabAtom";
import { AdvancedTab } from "./AdvancedTab";
import { DetailTab } from "./DetailTab";
import { IntroTab } from "./IntroTab";
import { ProfileTab } from "./ProfileTab";
import { PromptTab } from "./PromptTab";

const TABS: { id: CharacterBuilderTab; label: string }[] = [
  { id: "profile", label: "프로필" },
  { id: "intro", label: "인트로" },
  { id: "prompt", label: "프롬프트" },
  { id: "advanced", label: "고급기능" },
  { id: "detail", label: "상세" },
];

/** 400 응답 detail 중 `{missingFields}`(필수 항목 누락)와 `{reason}`(자동 필터 거부)를 구분한다
 * (techspec-backend-content.md §1.2/§1.3) — 전자는 토스트로 안내하고, 후자만 이의제기 진입점이
 * 있는 발행 거부 상태로 보여준다. */
function getFilterRejectionReason(error: unknown): string | null {
  const apiError = error as ApiError;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return null;
  if ("reason" in apiError.detail) return String(apiError.detail.reason);
  return null;
}

// characterBuilderSchema의 profile.image/registration.genre/registration.target은 초안 상태를
// 표현하기 위해 nullable이라(US-091), 발행 버튼의 safeParse 가드를 통과해도 이 값들이 비어 있을 수
// 있다 — 이 경우 서버(validate_character_publish)가 돌려주는 필드명을 한국어 라벨로 보여준다.
const MISSING_FIELD_LABELS: Record<string, string> = {
  name: "이름",
  oneLiner: "한줄소개",
  thumbnailAssetId: "대표 이미지",
  intro: "인트로",
  characterPrompt: "캐릭터 프롬프트",
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

type CharacterBuilderShellProps = {
  draft: CharacterDraftContent;
  draftId: string | null;
  renderPreview: (args: { getPayload: () => PreviewStartPayload; onClose: () => void }) => ReactNode;
};

/** techspec-builder-character.md §0/§1 — 5탭 단일 useForm 셸. 자동저장(US-096)/발행(US-083)/
 * 미리보기(US-088)를 여기서 연동한다.
 *
 * `draftId`는 아직 서버에 없는 초안이면 null이다(US-007) — 첫 저장이 초안을 만들고 URL을 바꾼다. */
export function CharacterBuilderShell({ draft, draftId, renderPreview }: CharacterBuilderShellProps) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useAtom(characterBuilderActiveTabAtom);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [rejectionReason, setRejectionReason] = useState<string | null>(null);
  const form = useForm<CharacterBuilderFormValues>({ defaultValues: serverToForm(draft) });
  const values = useWatch({ control: form.control });
  const canPublish = characterBuilderSchema.safeParse(values).success;

  const { saveDraft } = useDraftPersistence({ type: "character", draftId });
  const publishMutation = usePublishContentMutation();

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      const subscription = form.watch((formValues) => cb(formValues as CharacterBuilderFormValues));
      return () => subscription.unsubscribe();
    },
    formToServer,
    save: saveDraft,
    flushOnUnmount: () => draftId !== null,
  });

  /** 상황별 이미지 등록(`POST /assets/{id}/register-situational-image`)은 content_version_id를
   * 요구한다(US-071) — 초안이 아직 없으면 여기서 지금 폼 값으로 만들고, 이미 있으면 방금 입력한
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
    } catch {
      toast.error("임시저장에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  async function handlePublish() {
    setRejectionReason(null);
    const payload = formToServer(characterBuilderSchema.parse(form.getValues()));
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
          <h1 className="text-2xl font-bold break-keep tracking-tight text-foreground">캐릭터 만들기</h1>
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
            <p className="text-sm font-medium text-destructive">발행이 거부되었어요</p>
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

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as CharacterBuilderTab)}>
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
        <TabsContent value="intro">
          <IntroTab form={form} />
        </TabsContent>
        <TabsContent value="prompt">
          <PromptTab form={form} />
        </TabsContent>
        <TabsContent value="advanced">
          <AdvancedTab form={form} ensureContentVersionId={ensureContentVersionId} />
        </TabsContent>
        <TabsContent value="detail">
          <DetailTab form={form} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
