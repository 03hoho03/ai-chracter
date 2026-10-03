type RequiredTextProps = {
  children: React.ReactNode;
};

/**
 * 필수 입력 라벨의 글자 뒤에 빨간 별표를 붙인다.
 * 글자와 별표를 한 `<span>` 으로 묶는 이유: `<Label>` 은 `flex gap-2` 라 둘을 따로 두면 사이가
 * 띄어쓰기 한 칸이 아니라 8px 로 벌어진다. 별표는 숨기지 않아 접근 이름이 "이름 *" 그대로 남는다.
 */
export function RequiredText({ children }: RequiredTextProps) {
  return (
    <span>
      {children} <span className="text-destructive-text">*</span>
    </span>
  );
}
