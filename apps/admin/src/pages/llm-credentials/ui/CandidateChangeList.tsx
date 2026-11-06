import { axisNames } from "../model/axes";
import { groupCandidateChanges } from "../model/messages";
import type { CandidateChange } from "../model/status";

type CandidateChangeListProps = {
  changes: readonly CandidateChange[];
  /** 한쪽이 목록이 아니라 env 키다 — 목록 사용을 켤 때는 "env 키 → 항목", 끌 때는 "항목 → env 키". */
  across?: "from-env" | "to-env";
};

const NO_CANDIDATE_TEXT = "없음 — 이 모델 호출이 실패·환불돼요";

/** 모델마다 받는 항목이 어떻게 바뀌는지 — 같은 이동끼리 묶어 "Opus·Sonnet: 계정 A → 계정 B". 받을 항목이 없어지는 축만
 * 경고 글자다(목록이 쓰이는 동안 그 모델 호출은 env 키로 넘어가지 않고 실패한다). */
export function CandidateChangeList({ changes, across }: CandidateChangeListProps) {
  return (
    // Tailwind 기본 스타일이 목록 표식을 지우면 Safari(VoiceOver)가 목록의 뜻을 버려 role 로 되살린다.
    <ul role="list" className="flex flex-col gap-1 text-sm">
      {groupCandidateChanges(changes).map((group) => (
        <li key={group.axes.join("-")} className="break-keep wrap-anywhere">
          <span className="text-muted-foreground">{axisNames(group.axes)}:</span>{" "}
          <span className="text-foreground">{fromText(group.from?.label, across)}</span>
          <span className="text-muted-foreground"> → </span>
          {group.to === undefined && across !== "to-env" ? (
            <span className="text-destructive-text">{NO_CANDIDATE_TEXT}</span>
          ) : (
            <span className="text-foreground">{group.to?.label ?? "env 키"}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function fromText(label: string | undefined, across: CandidateChangeListProps["across"]): string {
  if (across === "from-env") return "env 키";
  return label ?? "없음";
}
