import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useState } from "react";
import { type Control, Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { isRoutingLane, PREMIUM_OFF_UNREAD_COPY, useRoutingQuery, type RoutingLane } from "@/entities/prompt-routing";
import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useDraftChangesQuery } from "../api/useDraftChangesQuery";
import { usePublishMutation } from "../api/usePublishMutation";
import { chainReaders } from "../model/chainReads";
import { promptSectionLabel } from "../model/channels";
import { PROMPT_LANE_LABELS, type PromptLane } from "../model/lane";
import { PROMPT_MODEL_LABELS, type PromptModel } from "../model/model";
import {
  DEFAULT_SEMVER_LEVEL,
  isSemverLevel,
  ruleDetail,
  SECTION_CHANGE_LABELS,
  SEMVER_LEVEL_LABELS,
  SEMVER_LEVELS,
  semverConflictMessage,
  type AdminPromptDraftChangesResponse,
  type SemverLevel,
} from "../model/semver";

/** `levels` 는 섹션 이름 → 고른 단계. 고르지 않은 섹션은 키가 없고 기본(patch)으로 읽는다 — 바뀐 섹션 목록을 다시 받으면
 * 사라진 섹션의 선택은 요청에서 빠지고 새로 생긴 섹션은 기본으로 시작한다(`levelsToSend`). */
type PublishFormValues = {
  note: string;
  levels: Partial<Record<string, SemverLevel>>;
};

type PublishPromptSetDialogProps = {
  lane: PromptLane;
  model: PromptModel;
};

// 채팅 밖 레인은 읽히는 자리가 정해져 있다. `publish_filter`는 채팅 턴이 아니라 제작자가 발행 버튼을 누를 때(다음 발행 심사부터)
// 읽힌다. 소설 레인 Gemini 세트는 경계 제안·문단 수정·여러 문단 수정·묶음 재검사와 Gemini 로 쓰는 화 생성·전체·장면 구성안에
// 읽힌다. 채팅 두 레인은 모델과 무관하게 모델 배정 표가 고른 칸에서 읽히므로 아래 `chatPublishEffectCopy` 가 배정 표 조회로
// 문장을 만든다.
const NON_CHAT_PUBLISH_EFFECT_COPY: Record<Exclude<PromptLane, RoutingLane>, string> = {
  publish_filter: "다음 발행 심사부터 즉시 반영되고",
  novel: "다음 소설 경계 제안·문단 수정·여러 문단 수정·묶음 재검사와 Gemini 로 쓰는 다음 화 생성·구성안부터 즉시 반영되고",
  novel_screen: "다음 노벨 공개 심사부터 즉시 반영되고",
};

/** 소설 레인 Claude 세트는 그 모델로 쓰는 화 생성·전체·장면 구성안에만 읽힌다(경계 제안·문단 수정·여러 문단 수정·묶음 재검사는
 * Gemini 세트). 상위 모델이 꺼져 있거나 허용이 없으면 그 자리도 Gemini 로 돌아 게시해도 아무 데도 쓰이지 않는다. */
const NOVEL_CLAUDE_PUBLISH_EFFECT_COPY =
  "이 모델로 쓰는 다음 소설 화 생성·구성안부터 즉시 반영되고(상위 모델이 꺼져 있거나 허용이 없으면 쓰이지 않아요)";

/** 채팅 레인 체인은 응답 생성이든 판정·요약이든 배정 표가 그 체인을 고른 칸에서만 읽힌다 — 읽는 칸 수는 배정 표 조회의 체인
 * 목록 하나에서 온다. 화자 라벨·등급 규칙은 소설이 원작의 채팅 Gemini 세트에서 읽으므로(배정 표와 무관하다) Gemini 체인에만
 * 그 괄호를 붙인다. */
function chatPublishEffectCopy(routingQuery: ReturnType<typeof useRoutingQuery>, lane: RoutingLane, model: PromptModel) {
  const novelNote = model === "gemini" ? "(화자 라벨과 등급 규칙은 다음 소설 작업에도 쓰여요)" : "";
  if (routingQuery.isPending) return `운영에서 이 체인을 읽는 칸을 확인하는 중이고${novelNote}`;
  if (routingQuery.isError) return `운영에서 이 체인을 읽는 칸을 확인하지 못했고(모델 배정 화면에서 확인하세요)${novelNote}`;
  const { live, switchedOff } = chainReaders(routingQuery.data, lane, model);
  const offNote = switchedOff.length > 0 ? `(Opus 방 ${switchedOff.length}칸은 ${PREMIUM_OFF_UNREAD_COPY})` : "";
  if (live.length === 0) return `지금은 이 체인을 읽는 칸이 없어 게시해도 바로 쓰이지 않고${offNote}${novelNote}`;
  return `이 체인을 읽는 칸(${live.length}칸)의 다음 턴부터 즉시 반영되고${offNote}${novelNote}`;
}

/** 게시는 그 체인을 읽는 자리에 즉시 반영되는 되돌리기 어려운 행동이라 다이얼로그로 한 번
 * 더 확인받는다 — legal의 `PublishDialog`와 같은 어휘(react-call, 자체 호출형). 버전은
 * 서버가 자동 증가로 부여하므로 입력받지 않는다.
 *
 * 판(semver)은 섹션마다 단계를 고르고 체인 판은 서버가 고른 단계 중 가장 큰 것으로 올린다. 결과 번호를 화면이 미리 계산하지
 * 않는다 — 서버는 섹션의 지금 판이 아니라 그 섹션이 가졌던 가장 큰 판에서 올리므로(섹션 복원 뒤에는 둘이 다르다) 화면 계산이
 * 틀릴 수 있다. 번호는 게시 응답으로 알린다.
 *
 * 게시 검증 규칙 위반(422)은 이 다이얼로그의 어느 입력값과도 무관한 구조적 문제라 필드 에러로
 * 붙이지 않는다 — 닫고 토스트로 알려 어드민이 어느 섹션을 고쳐야 하는지 보게 한다. 단, 단계를 고른 뒤 바뀐 섹션이 달라졌다는
 * 거부는 모달을 닫지 않고 목록을 다시 받아 다시 고르게 한다. */
export const PublishPromptSetDialog = createCallable<PublishPromptSetDialogProps, void>(({ call, lane, model }) => {
  const publishMutation = usePublishMutation(lane, model);
  const routingQuery = useRoutingQuery();
  const changesQuery = useDraftChangesQuery(lane, model, !call.ended);
  const [conflictMessage, setConflictMessage] = useState<string>();
  const chainName = `${PROMPT_LANE_LABELS[lane]} · ${PROMPT_MODEL_LABELS[model]}`;
  const {
    control,
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<PublishFormValues>({ defaultValues: { note: "", levels: {} } });

  const publishEffectCopy = (): string => {
    if (isRoutingLane(lane)) return chatPublishEffectCopy(routingQuery, lane, model);
    return model === "gemini" ? NON_CHAT_PUBLISH_EFFECT_COPY[lane] : NOVEL_CLAUDE_PUBLISH_EFFECT_COPY;
  };

  const changes = changesQuery.data;
  // 다시 받는 동안이나 다시 받기에 실패했을 때는 화면의 목록이 서버와 다를 수 있어 게시를 막는다.
  const isChangesReady = changes !== undefined && !changesQuery.isFetching && !changesQuery.isError;

  const onSubmit = async (values: PublishFormValues) => {
    if (!isChangesReady) return;
    try {
      const published = await publishMutation.mutateAsync({
        note: values.note,
        levels: levelsToSend(changes, values.levels),
        // 기준판이 없어도(첫 판) 키를 보낸다 — 서버는 "보냈는가"로 기준판 대조 여부를 가른다.
        baseSetId: changes.baseSetId,
        draftHash: changes.draftHash,
      });
      // 버전은 레인·모델과 무관하게 전역 단조라 이 체인의 직전 버전과 번호가 안 이어질 수
      // 있다(예: story v3 다음이 v5).
      const semverText = published.semver ? `(판 ${published.semver})` : "";
      toast.success(
        `${chainName} v${published.version}${semverText}을(를) 게시했어요. 버전 번호는 레인·모델과 무관하게 전역으로 매겨져요.`,
      );
      call.end();
    } catch (error) {
      const conflict = semverConflictMessage(error);
      if (conflict !== null) {
        setConflictMessage(conflict);
        void changesQuery.refetch();
        return;
      }
      const detail = isApiError(error) && error.status === 422 ? ruleDetail(error) : null;
      if (detail) {
        toast.error(`${detail.rule}: ${detail.message}`);
      } else {
        toast.error("게시에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
      call.end();
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>프롬프트 세트 게시</DialogTitle>
          <DialogDescription className="break-keep">
            지금 저장된 <span className="font-medium text-foreground">{chainName}</span> 초안을 새 버전으로
            게시해요. {publishEffectCopy()}, 초안은 게시 후에도 그대로 남아요.
          </DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(onSubmit)(event);
          }}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <DialogBody scrollLabel="바뀐 섹션" className="flex flex-col gap-4">
            {conflictMessage !== undefined && (
              <p role="alert" className="break-keep rounded-lg border border-border px-3 py-2 text-sm text-foreground">
                {conflictMessage} 아래 목록을 다시 받았어요 — 단계를 확인한 뒤 다시 게시하세요.
              </p>
            )}

            {changesQuery.isPending && (
              <div className="flex flex-col gap-2" aria-busy>
                <span className="sr-only">바뀐 섹션을 불러오는 중이에요</span>
                <div className="h-10 animate-pulse rounded-lg bg-secondary" />
                <div className="h-10 animate-pulse rounded-lg bg-secondary" />
                <div className="h-10 animate-pulse rounded-lg bg-secondary" />
              </div>
            )}

            {changesQuery.isError && (
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm text-destructive-text">바뀐 섹션을 불러오지 못했어요.</p>
                <Button type="button" variant="outline" size="sm" onClick={() => void changesQuery.refetch()}>
                  다시 시도
                </Button>
              </div>
            )}

            {changes && (
              <SectionLevelList changes={changes} control={control} isRefetching={changesQuery.isFetching} />
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="prompt-publish-note">메모</Label>
              <Textarea
                id="prompt-publish-note"
                placeholder="왜 바꿨는지 남겨두면 나중에 롤백할 때 도움이 돼요."
                {...register("note")}
              />
            </div>
          </DialogBody>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus onClick={() => call.end()}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting || !isChangesReady}>
              {isSubmitting ? "게시 중..." : "게시"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

/** 요청에는 지금 목록에서 바뀐 섹션의 단계만 싣는다. 첫 판은 단계를 고를 것이 없어 빈 객체다. */
function levelsToSend(
  changes: AdminPromptDraftChangesResponse,
  chosen: Partial<Record<string, SemverLevel>>,
): Record<string, SemverLevel> {
  if (changes.baseSetId === null) return {};
  return Object.fromEntries(
    changedSections(changes).map((section) => [section.channel, chosen[section.channel] ?? DEFAULT_SEMVER_LEVEL]),
  );
}

function changedSections(changes: AdminPromptDraftChangesResponse) {
  return changes.sections.filter((section) => section.change !== "unchanged" && section.change !== "initial");
}

type SectionLevelListProps = {
  changes: AdminPromptDraftChangesResponse;
  control: Control<PublishFormValues>;
  /** 목록을 다시 받는 중이면 고르지 못하게 한다(받은 뒤 사라질 섹션일 수 있다). */
  isRefetching: boolean;
};

/** 첫 판·바뀐 섹션 없음·섹션별 단계 선택 셋으로 갈린다. 바뀐 섹션이 없어도 게시할 수 있다(체인 판만 patch 로 오른다). */
function SectionLevelList({ changes, control, isRefetching }: SectionLevelListProps) {
  if (changes.baseSetId === null) {
    return (
      <p className="break-keep text-sm text-foreground">
        이 체인의 첫 판이에요. 체인과 모든 섹션이 1.0.0 으로 시작해요.
      </p>
    );
  }

  const sections = changedSections(changes);
  const baseText = changes.baseSemver ?? "판 없음";

  if (sections.length === 0) {
    return (
      <p className="break-keep text-sm text-foreground">
        바뀐 섹션이 없어요. 체인 판만 patch 로 올라가요(지금 {baseText}).
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="break-keep text-xs text-muted-foreground">
        섹션마다 판 단계를 고르세요. 체인 판은 고른 단계 중 가장 큰 단계로 올라가요(지금 {baseText}). 새 번호는 게시한
        뒤에 알려 드려요.
      </p>
      <ul className="flex flex-col gap-2">
        {sections.map((section) => {
          const label = promptSectionLabel(section.channel);
          return (
            <li
              key={section.channel}
              className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="font-medium break-keep text-foreground">{label}</span>
                <span className="inline-flex rounded-full border border-border px-2 py-0.5 text-badge font-medium text-foreground">
                  {SECTION_CHANGE_LABELS[section.change]}
                </span>
                <span className="text-xs text-muted-foreground tabular-nums">
                  지금 {section.currentSemver ?? "새 섹션"}
                </span>
              </div>
              <Controller
                control={control}
                name={`levels.${section.channel}`}
                render={({ field }) => (
                  <ToggleGroup
                    type="single"
                    variant="neutral"
                    size="sm"
                    value={field.value ?? DEFAULT_SEMVER_LEVEL}
                    onValueChange={(next) => {
                      // 단일 토글 그룹은 고른 항목을 다시 누르면 빈 값을 보낸다 — 판 단계는 늘 하나가 골라져 있어야 해 버린다.
                      if (isSemverLevel(next)) field.onChange(next);
                    }}
                    aria-label={`${label} 판 단계`}
                    disabled={isRefetching}
                    className="shrink-0"
                  >
                    {SEMVER_LEVELS.map((level) => (
                      <ToggleGroupItem key={level} value={level}>
                        {SEMVER_LEVEL_LABELS[level]}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                )}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
