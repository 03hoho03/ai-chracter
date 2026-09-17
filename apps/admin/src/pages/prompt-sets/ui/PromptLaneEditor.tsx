import { useDraftQuery } from "../api/useDraftQuery";
import { useVersionListQuery } from "../api/useVersionListQuery";
import type { PromptLane } from "../model/lane";
import { PromptLaneForm } from "./PromptLaneForm";

type PromptLaneEditorProps = {
  lane: PromptLane;
};

/** prompt-scope-techspec.md §6-1 — `draft`가 non-null이어야 `PromptLaneForm`의
 * `useMemo(() => serverToForm(draft), [draft])`가 안전하다는 불변식을 이 로딩/에러 분기가
 * 지킨다. 활성 버전 배지는 자기 쿼리 상태를 직접 가르는 `ActiveVersionBadge`로 갈라낸다
 * (`VersionHistorySection`의 `VersionTable`과 같은 결) — 합쳐서 읽으면 목록 요청이 로딩·실패
 * 중에도 "아직 게시된 버전이 없어요"로 보인다. */
export function PromptLaneEditor({ lane }: PromptLaneEditorProps) {
  const draftQuery = useDraftQuery(lane);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <ActiveVersionBadge lane={lane} />
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

      {draftQuery.data && <PromptLaneForm lane={lane} draft={draftQuery.data} />}
    </div>
  );
}

type ActiveVersionBadgeProps = {
  lane: PromptLane;
};

/** 이 레인 값만 읽는다(TS-J) — 옛 `PageHeader`의 `items.find(isActive)`는 활성본이 셋이 되는
 * 순간 아무거나 집는 결함이 있었다. 로딩·에러를 "게시 이력 없음"과 분리한다 — 목록 요청이
 * 실패한 순간에도 실제로는 활성 버전이 있을 수 있다. */
function ActiveVersionBadge({ lane }: ActiveVersionBadgeProps) {
  const versionListQuery = useVersionListQuery();

  if (versionListQuery.isPending) {
    return <span className="text-sm text-muted-foreground">활성 버전 확인 중...</span>;
  }

  if (versionListQuery.isError) {
    return <span className="text-sm text-destructive-text">활성 버전을 확인하지 못했어요.</span>;
  }

  const activeVersion = versionListQuery.data.items.find((item) => item.isActive && item.lane === lane);

  return (
    <span className="text-sm text-muted-foreground">
      {activeVersion ? `현재 활성 버전 v${activeVersion.version}` : "아직 게시된 버전이 없어요"}
    </span>
  );
}
