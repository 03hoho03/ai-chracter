/** 목업의 여러 줄 칸이 접힌 상태에서 보이는 줄 수. 빌더 칸처럼 "여러 줄 칸"으로 읽히되 페이지가 길어지지 않는 값이다. */
export const MOCKUP_CLAMP_LINES = 4;

/**
 * 390px 폭 목업 칸 안쪽(약 308px)에 한 줄로 들어가는 글자 수를 보수적으로 잡은 값. 한글 한 글자가 최대 16px 이고
 * 어절 단위 줄바꿈이 줄 끝에서 몇 글자를 버리므로 실제보다 적게 잡는다 — 적게 잡을수록 "전체 보기"가 필요 없는 칸에 남을
 * 뿐이고, 필요한 칸에서 빠지지는 않는다.
 */
const CHARS_PER_LINE = 18;

/**
 * 값이 접힌 줄 수를 넘는지 — 넘을 때만 "전체 보기"를 그린다. 렌더 뒤 높이를 재지 않고 글자로 정하는 이유: 재면 처음 그릴
 * 때와 잰 뒤의 모양이 달라 한 번 깜빡이고, 그 측정을 칸마다 붙여야 한다. 대가로 넓은 화면에서 4줄 안에 다 들어가는 값에도
 * "전체 보기"가 남을 수 있다(눌러도 거의 바뀌지 않는다).
 */
export function exceedsClampLines(text: string): boolean {
  const lineCount = text
    .split("\n")
    .reduce((sum, line) => sum + Math.max(1, Math.ceil([...line].length / CHARS_PER_LINE)), 0);
  return lineCount > MOCKUP_CLAMP_LINES;
}
