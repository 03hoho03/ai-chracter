import { useDraftQuery } from "../api/useDraftQuery";
import { useVersionListQuery } from "../api/useVersionListQuery";
import type { PromptLane } from "../model/lane";
import { PromptLaneForm } from "./PromptLaneForm";

type PromptLaneEditorProps = {
  lane: PromptLane;
};

/** prompt-scope-techspec.md §6-1 — `draft`가 non-null이어야 `PromptLaneForm`의
 * `useMemo(() => serverToForm(draft), [draft])`가 안전하다는 불변식을 이 로딩/에러 분기가
 * 지킨다. 활성 버전 배지도 여기서 이 레인 값만 읽는다(TS-J) — 옛 `PageHeader`의
 * `items.find(isActive)`는 활성본이 셋이 되는 순간 아무거나 집는 결함이 있었다. */
export function PromptLaneEditor({ lane }: PromptLaneEditorProps) {
  const draftQuery = useDraftQuery(lane);
  const versionListQuery = useVersionListQuery();
  const activeVersion = versionListQuery.data?.items.find((item) => item.isActive && item.lane === lane);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <span className="text-sm text-muted-foreground">
          {activeVersion ? `현재 활성 버전 v${activeVersion.version}` : "아직 게시된 버전이 없어요"}
        </span>
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
