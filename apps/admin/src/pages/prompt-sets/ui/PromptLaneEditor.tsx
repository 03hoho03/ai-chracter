import { isRoutingLane } from "@/entities/prompt-routing";

import { useDraftQuery } from "../api/useDraftQuery";
import { useVersionListQuery } from "../api/useVersionListQuery";
import type { PromptLane } from "../model/lane";
import { PROMPT_MODEL_LABELS, type PromptChainKey, type PromptModel } from "../model/model";
import { ChainReadBy } from "./ChainReadBy";
import { PromptLaneForm } from "./PromptLaneForm";

type PromptLaneEditorProps = {
  lane: PromptLane;
  model: PromptModel;
  onDirtyChange: (chain: PromptChainKey, isDirty: boolean) => void;
};

/** `draft`가 non-null이어야 `PromptLaneForm`의
 * `useMemo(() => serverToForm(draft), [draft])`가 안전하다는 불변식을 이 로딩/에러 분기가
 * 지킨다. 활성 버전 배지는 자기 쿼리 상태를 직접 가르는 `ActiveVersionBadge`로 갈라낸다
 * (`VersionHistorySection`의 `VersionTable`과 같은 결) — 합쳐서 읽으면 목록 요청이 로딩·실패
 * 중에도 "아직 게시된 버전이 없어요"로 보인다. */
export function PromptLaneEditor({ lane, model, onDirtyChange }: PromptLaneEditorProps) {
  const draftQuery = useDraftQuery(lane, model);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
        {/* Gemini 가 아닌 세트에는 그 모델이 쓸 수 있는 채널만 있다 — 나머지 채널 탭이 왜 없는지, 이 세트의 어느 문안이
         * 언제 쓰이는지를 편집 전에 밝힌다. 채팅 레인 Claude 세트는 생성 두 채널과 판정·요약 채널, 판정 전용 세트는
         * 판정·요약 채널만, 소설 레인은 화 생성과 전체·장면 구성안 세 채널이다. 채팅 레인의 판정·요약 문안은 모델 배정 표가
         * 그 체인을 고른 칸에서 읽힌다 — 지금 어느 칸이 읽는지를 배정 표 조회로 바로 아래에 보여, 고쳤는데 판정이 안 바뀐다는
         * 오해를 막는다. */}
        <div className="flex min-w-0 flex-col gap-1">
          {model !== "gemini" && (
            <p className="max-w-prose break-keep text-xs text-muted-foreground">{nonGeminiGuide(lane, model)}</p>
          )}
          {isRoutingLane(lane) && <ChainReadBy lane={lane} model={model} />}
        </div>
        <ActiveVersionBadge lane={lane} model={model} />
      </div>

      {draftQuery.isPending && (
        <>
          <div className="h-24 animate-pulse rounded-xl bg-muted" />
          <div className="h-96 animate-pulse rounded-xl bg-muted" />
        </>
      )}

      {draftQuery.isError && (
        <p className="text-sm text-destructive-text">초안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {draftQuery.data && (
        <PromptLaneForm
          lane={lane}
          model={model}
          draft={draftQuery.data}
          onDirtyChange={onDirtyChange}
        />
      )}
    </div>
  );
}

function nonGeminiGuide(lane: PromptLane, model: PromptModel): string {
  if (lane === "novel") {
    return `${PROMPT_MODEL_LABELS[model]} 세트는 이 모델로 쓰는 소설 화 생성과 전체·장면 구성안에만 쓰여요. 경계 제안·문단 수정·여러 문단 수정·묶음 재검사는 고른 모델과 상관없이 소설 Gemini 세트를, 화자 라벨·등급 규칙은 원작의 채팅 Gemini 세트를 읽어요.`;
  }
  if (model === "haiku") {
    return "이 세트에는 판정(스탯·장면 헤더·엔딩·이미지)과 기억 요약·추출 문안만 있어요. 모델 배정 표가 이 체인을 고른 칸에서만 쓰이고, 고른 칸이 없으면 env 판정 모델의 체인이 쓰여요. 이 모델로는 응답을 쓰지 않아요.";
  }
  return `${PROMPT_MODEL_LABELS[model]} 세트의 시스템 지침·생성 문안은 이 모델을 고른 방의 응답 생성에 쓰여요. 판정·요약 문안은 모델 배정 표가 이 체인을 고른 칸에서 쓰여요(지금 읽는 칸은 아래 표시). 소설은 소설 레인 세트를 읽어요.`;
}

type ActiveVersionBadgeProps = {
  lane: PromptLane;
  model: PromptModel;
};

/** 이 (레인, 모델) 체인 값만 읽는다 — 목록의 활성본은 체인마다 하나라 레인만 맞추면 다른 모델의 활성본을 집는다(옛
 * `PageHeader`의 `items.find(isActive)`가 활성본이 셋이 되는 순간 아무거나 집던 것과 같은 결함). 로딩·에러를 "게시 이력 없음"과 분리한다 — 목록 요청이
 * 실패한 순간에도 실제로는 활성 버전이 있을 수 있다. */
function ActiveVersionBadge({ lane, model }: ActiveVersionBadgeProps) {
  const versionListQuery = useVersionListQuery();

  if (versionListQuery.isPending) {
    return <span className="text-sm text-muted-foreground">활성 버전 확인 중...</span>;
  }

  if (versionListQuery.isError) {
    return <span className="text-sm text-destructive-text">활성 버전을 확인하지 못했어요.</span>;
  }

  const activeVersion = versionListQuery.data.items.find(
    (item) => item.isActive && item.lane === lane && item.model === model,
  );

  return (
    <span className="shrink-0 text-sm text-muted-foreground sm:ml-auto">
      {activeVersion ? `현재 활성 버전 v${activeVersion.version}` : "아직 게시된 버전이 없어요"}
    </span>
  );
}
