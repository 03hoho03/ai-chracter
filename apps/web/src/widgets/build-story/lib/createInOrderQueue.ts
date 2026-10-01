/**
 * 0, 1, 2… 번 결과가 아무 순서로 도착해도 `apply` 는 번호 순서대로 부른다. 앞 번호가 아직이면 뒤 번호는 기다린다.
 *
 * 일괄 업로드는 파일 몇 개를 동시에 올려 끝나는 순서가 매번 다르다. 끝나는 대로 폼에 반영하면 새 인물·장면이 끝난
 * 순서로 만들어져(예: `s02, s03, s01`) 작가가 파일 이름으로 정한 순서가 깨진다 — 반영만 파일 순서로 줄 세운다.
 */
export function createInOrderQueue<T>(apply: (index: number, value: T) => void): (index: number, value: T) => void {
  // 값이 undefined 일 수도 있어 "도착했는가"를 칸의 유무로 가른다.
  const arrived = new Map<number, { value: T }>();
  let next = 0;
  return (index, value) => {
    arrived.set(index, { value });
    for (let slot = arrived.get(next); slot !== undefined; slot = arrived.get(next)) {
      arrived.delete(next);
      apply(next, slot.value);
      next += 1;
    }
  };
}
