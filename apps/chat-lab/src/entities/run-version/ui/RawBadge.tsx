type RawBadgeProps = {
  /** 표·띠의 좁은 칸이면 "원문", 그 밖(미리보기·상세 머리·지우기 확인)은 "원문 포함". */
  isCompact?: boolean;
};

const RAW_BADGE_TITLE = "이 판은 원문을 담았다 — 프롬프트·지시문·기억 노트·요약 본문이 들어 있다";

/**
 * 원문 포함 판의 표지. 형식 배지 `이전` 과 같은 테두리 칩이고 글자만 `ink` 로 진하다. 원문 제외는 아무 표시가 없다 — 정상이 가장
 * 조용해야 한다. 이름 칸 안에서 `shrink-0` 이라 이름이 잘려도 남고, `이전` 과 한 행에 서면 그 뒤에 선다(낱말 말고 자리로도 갈린다).
 */
export function RawBadge({ isCompact = false }: RawBadgeProps) {
  return (
    <span
      title={RAW_BADGE_TITLE}
      className="inline-flex h-4.5 shrink-0 items-center rounded-sm border border-border-strong px-1.5 text-label whitespace-nowrap text-ink"
    >
      {isCompact ? "원문" : "원문 포함"}
    </span>
  );
}
