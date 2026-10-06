type ProposalLike = {
  candidates: readonly { messageId: string }[];
  suggestion: { endMessageId: string } | null;
};

/** 장 끝 고르기를 열 때 미리 골라 둘 턴. AI 제안이 후보 안에 있으면 그 턴이고, 제안이 없거나(모델 실패) 후보
 * 밖을 가리키면 아무것도 고르지 않는다 — 엉뚱한 턴을 대신 골라 두면 이용자가 확인 없이 그대로 만들 수 있다. */
export function toInitialChapterEnd(proposal: ProposalLike): string | undefined {
  const suggested = proposal.suggestion?.endMessageId;
  if (suggested === undefined) return undefined;
  return proposal.candidates.some((candidate) => candidate.messageId === suggested) ? suggested : undefined;
}
