import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useMemo, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";

import { usePreviewQuery } from "../api/usePreviewQuery";
import { useSaveDraftMutation } from "../api/useSaveDraftMutation";
import { PROMPT_CHANNELS, PROMPT_CHANNEL_LABELS, isPromptChannel, type PromptChannel } from "../model/channels";
import type { PromptLane } from "../model/lane";
import {
  formToServer,
  promptSetFormSchema,
  serverToForm,
  type AdminPromptDraftResponse,
  type PromptSetFormValues,
} from "../model/schema";
import { ChannelSectionList } from "./ChannelSectionList";
import { LabelsCard } from "./LabelsCard";
import { PreviewPanel } from "./PreviewPanel";
import { PublishPromptSetDialog } from "./PublishPromptSetDialog";

type PromptLaneFormProps = {
  lane: PromptLane;
  draft: AdminPromptDraftResponse;
};

/** 현행 `PromptSetsEditor`의 몸통 그대로. `PromptLaneEditor`와
 * 2단으로 갈린 이유가 아래 `values`의 불변식이다 — 한 컴포넌트로 합치지 않는다. */
export function PromptLaneForm({ lane, draft }: PromptLaneFormProps) {
  // `values`는 참조가 바뀔 때마다 RHF의 동기화 effect를 다시 태운다 — 매 렌더 새 객체를
  // 넘기면(예: 인라인 `serverToForm(draft)`) 내용이 같아도 매번 재동기화가 돌아 `isDirty`가
  // 타이핑 도중 조용히 꺼진다(실측: 라벨 입력은 안 먹고 `setValue`만 먹혔다). `draft`가
  // 실제로 바뀔 때만(저장/복원 성공 시) 새 객체를 만든다.
  const values = useMemo(() => serverToForm(draft), [draft]);
  const form = useForm<PromptSetFormValues>({
    resolver: zodResolver(promptSetFormSchema),
    values,
  });
  const saveDraftMutation = useSaveDraftMutation(lane);
  // `PreviewPanel`도 같은 queryKey로 이 쿼리를 부른다 — react-query가 캐시를 공유해 요청이
  // 중복되지 않는다(`PageHeader`/`VersionHistorySection`이 `useVersionListQuery`를 각자
  // 부르는 것과 같은 패턴). 게시 버튼이 "미리보기를 실제로 봤는가"를 알아야 해서 여기서도
  // 구독한다.
  const previewQuery = usePreviewQuery(lane);

  // 채널은 이 레인의 초안이 실제로 들고 있는 섹션에서
  // 도출한다. 손으로 `Record<PromptLane, PromptChannel[]>`을 적으면 BE
  // `_EXPECTED_ROWS_BY_LANE`(admin/prompts.py)과 같은 사실의 두 번째 사본이 된다.
  const channels = PROMPT_CHANNELS.filter((c) => draft.sections.some((s) => s.channel === c));
  // ⚠️ 초기값을 `"system"` 리터럴로 고정하면 `system` 채널이 없는 `publish_filter` 레인이
  // 빈 화면이 된다(가장 조용한 회귀) — `channels[0]`에서 도출한다.
  const [activeChannel, setActiveChannel] = useState<PromptChannel>(() => channels[0] ?? "system");

  const isDirty = form.formState.isDirty;
  const draftId = draft.id;

  const handleSave = form.handleSubmit(
    async (values) => {
      try {
        await saveDraftMutation.mutateAsync(formToServer(values));
        toast.success("초안을 저장했어요.");
      } catch {
        toast.error("저장에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    },
    () => toast.error("입력값을 확인해주세요."),
  );

  // 조립 결과를 실제로 본 뒤에만 게시할 수 있어야 한다. 초안이 이미 저장돼 있는(가장
  // 흔한) 상태로 페이지에 막 들어오면 `isDirty`도 false, `draftId`도 non-null이라 그 둘만
  // 보면 미리보기가 아직 로딩 중이거나 실패했어도 게시 버튼이 활성으로 뜬다(적대적 리뷰가
  // 브라우저로 재현) — `previewQuery` 상태를 반드시 함께 봐야 한다.
  let actionDisabledReason: string | undefined;
  if (isDirty) {
    actionDisabledReason = "저장하지 않은 변경사항이 있어요. 먼저 저장하세요.";
  } else if (draftId === null) {
    actionDisabledReason = "초안을 먼저 저장하세요.";
  } else if (previewQuery.isPending) {
    actionDisabledReason = "미리보기를 불러오는 중이에요. 확인한 뒤 게시할 수 있어요.";
  } else if (previewQuery.isError) {
    actionDisabledReason = "미리보기를 불러오지 못했어요. 위에서 다시 시도한 뒤 게시하세요.";
  }

  return (
    <FormProvider {...form}>
      <div className="flex flex-col gap-6">
        <LabelsCard lane={lane} />

        <section className="flex flex-col gap-3">
          <Tabs
            value={activeChannel}
            onValueChange={(value) => {
              if (isPromptChannel(value)) setActiveChannel(value);
            }}
          >
            {/* 채널 6개 + 라벨이 길어(예: "스탯 판정") 사이드바(w-56)가 폭을 뺏는 admin 좁은
             * 화면에서 TabsList 자체 폭을 넘긴다 — `overflow-x-auto`로 이 줄만 가로 스크롤하게
             * 해 페이지 전체가 넘치지 않게 한다. */}
            <div className="overflow-x-auto">
              <TabsList variant="line">
                {channels.map((channel) => (
                  <TabsTrigger key={channel} value={channel}>
                    {PROMPT_CHANNEL_LABELS[channel]}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>

            {channels.map((channel) => (
              <TabsContent key={channel} value={channel} className="pt-4">
                <ChannelSectionList channel={channel} />
              </TabsContent>
            ))}
          </Tabs>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={!isDirty || saveDraftMutation.isPending} onClick={() => void handleSave()}>
              {saveDraftMutation.isPending ? "저장 중..." : "초안 저장"}
            </Button>
            {isDirty && (
              <span className="text-xs font-medium text-muted-foreground">저장하지 않은 변경사항이 있어요</span>
            )}
          </div>
        </section>

        <PreviewPanel lane={lane} isStale={isDirty} />

        <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4">
          <h2 className="text-lg font-semibold text-foreground">게시</h2>
          <p className="break-keep text-xs text-muted-foreground">
            위 미리보기에서 조립 결과를 확인한 뒤 게시하세요. 버전 번호는 서버가 자동으로
            매겨요.
          </p>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!!actionDisabledReason}
              onClick={() => void PublishPromptSetDialog.call({ lane })}
            >
              게시
            </Button>
            {actionDisabledReason && (
              <span className="text-xs text-muted-foreground">{actionDisabledReason}</span>
            )}
          </div>
        </section>
      </div>
    </FormProvider>
  );
}
