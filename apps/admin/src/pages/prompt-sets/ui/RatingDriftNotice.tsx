type RatingDriftNoticeProps = {
  lines: readonly string[];
  /** 목록 뒤에 붙는 안내(게시 전·복원 뒤에 따라 다르다). */
  footer: string;
};

/** 채팅·소설 등급 규칙이 갈렸다는 확인 문장. 막지 않고 알리기만 한다 — 소설 등급 규칙은 채팅 값에서 옮겨 온 사본이라 한쪽만
 * 고치면 두 레인의 수위 규칙이 조용히 달라진다. */
export function RatingDriftNotice({ lines, footer }: RatingDriftNoticeProps) {
  if (lines.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground">
      <ul className="flex flex-col gap-1">
        {lines.map((line) => (
          <li key={line} className="break-keep">
            {line}
          </li>
        ))}
      </ul>
      <p className="break-keep text-xs text-muted-foreground">{footer}</p>
    </div>
  );
}
