type ValueChangeProps = {
  before: string;
  after: string;
};

/** "꺼짐 → 켜짐". 화살표는 읽히지 않아 화면 읽기에는 "꺼짐 에서 켜짐"으로 들린다. 숨김 글자가 스크롤 상자 밖 문서 높이를
 * 늘리지 않게, 이걸 담는 스크롤 상자(표 래퍼·모달 본문)는 위치 기준(`relative`)이어야 한다. */
export function ValueChange({ before, after }: ValueChangeProps) {
  return (
    <>
      {before}
      <span aria-hidden> → </span>
      <span className="sr-only"> 에서 </span>
      {after}
    </>
  );
}
