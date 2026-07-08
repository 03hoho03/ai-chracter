import { useState } from "react";
import type { ApiError, components } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { usePublishContentMutation, useUpdateContentDraftMutation } from "../../../entities/content";
import {
  characterBuilderSchema,
  formToServer,
  serverToForm,
  type CharacterBuilderFormValues,
} from "../../../features/build-character";
import { useAutosave } from "../../../features/build-common";
import { AppealModal } from "../../../features/submit-appeal";
import { PreviewSessionView } from "../../preview-session";
import { characterBuilderActiveTabAtom, type CharacterBuilderTab } from "../model/activeTabAtom";
import { AdvancedTab } from "./AdvancedTab";
import { DetailTab } from "./DetailTab";
import { IntroTab } from "./IntroTab";
import { ProfileTab } from "./ProfileTab";
import { PromptTab } from "./PromptTab";

type CharacterDraftResponse = components["schemas"]["CharacterDraftResponse"];

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

/** techspec-builder-character.md §0/§1 — 5탭 단일 useForm 셸. 자동저장(US-096)/발행(US-083)/
 * 미리보기(US-088)를 여기서 연동한다. */
export function CharacterBuilderShell({ data }: { data: CharacterDraftResponse }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useAtom(characterBuilderActiveTabAtom);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [rejectionReason, setRejectionReason] = useState<string | null>(null);
  const form = useForm<CharacterBuilderFormValues>({ defaultValues: serverToForm(data) });
  const values = useWatch({ control: form.control });
  const canPublish = characterBuilderSchema.safeParse(values).success;

  const updateDraftMutation = useUpdateContentDraftMutation(data.id);
  const publishMutation = usePublishContentMutation(data.id);

  const { saveNow } = useAutosave({
    subscribe: (cb) => {
      const subscription = form.watch((formValues) => cb(formValues as CharacterBuilderFormValues));
      return () => subscription.unsubscribe();
    },
    formToServer,
    save: (payload) => updateDraftMutation.mutateAsync(payload).then(() => undefined),
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
    const payload = formToServer(characterBuilderSchema.parse(form.getValues()));
    try {
      await updateDraftMutation.mutateAsync(payload);
      const result = await publishMutation.mutateAsync();
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
    }
  }

  if (isPreviewOpen) {
    return (
      <PreviewSessionView
        getPayload={() => formToServer(form.getValues())}
        onClose={() => setIsPreviewOpen(false)}
      />
    );
  }

  const isPublishing = updateDraftMutation.isPending || publishMutation.isPending;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">캐릭터 만들기</h1>
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
      </header>

      {rejectionReason && (
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
              void AppealModal.call({ target: { kind: "publish-rejection", rejectionId: data.id } })
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
          <AdvancedTab form={form} contentVersionId={data.contentVersionId} />
        </TabsContent>
        <TabsContent value="detail">
          <DetailTab form={form} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
