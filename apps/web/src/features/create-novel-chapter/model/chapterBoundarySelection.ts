type ProposalLike = {
  candidates: readonly { messageId: string }[];
  suggestion: { endMessageId: string } | null;
};

/** 화 끝 고르기를 열 때 미리 골라 둘 턴. AI 제안이 후보 안에 있으면 그 턴이고, 제안이 없거나(모델 실패) 후보
 * 밖을 가리키면 아무것도 고르지 않는다 — 엉뚱한 턴을 대신 골라 두면 이용자가 확인 없이 그대로 만들 수 있다. */
export function toInitialChapterEnd(proposal: ProposalLike): string | undefined {
  const suggested = proposal.suggestion?.endMessageId;
  if (suggested === undefined) return undefined;
  return proposal.candidates.some((candidate) => candidate.messageId === suggested) ? suggested : undefined;
}

/** 모델을 바꿔 그 모델의 후보를 다시 받은 뒤 골라 둘 턴. 모델마다 한 번에 담을 수 있는 턴 수가 달라 후보 목록이
 * 줄거나 늘어난다.
 *
 * - 고른 턴이 새 목록에도 있으면 그대로 둔다 — 이용자가 고른 것을 모델을 바꿨다고 옮기지 않는다.
 * - 새 목록 밖이면(더 짧게 담는 모델로 바꿨다) 그 모델이 담을 수 있는 마지막 턴으로 당긴다. 고른 자리에 가장 가까운
 *   턴이고, 아무것도 고르지 않은 채로 두면 이용자가 바꾼 모델 때문에 고르기를 처음부터 다시 해야 한다.
 * - 아직 아무것도 안 골랐으면 새 제안을 처음 열 때처럼 골라 둔다. */
export function toChapterEndAfterModelChange(
  selectedId: string | undefined,
  proposal: ProposalLike,
): string | undefined {
  if (selectedId === undefined) return toInitialChapterEnd(proposal);
  if (proposal.candidates.some((candidate) => candidate.messageId === selectedId)) return selectedId;
  return proposal.candidates.at(-1)?.messageId;
}
