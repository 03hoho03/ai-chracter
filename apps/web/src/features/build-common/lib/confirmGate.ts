/**
 * 확인 하나가 진행 중이면 뒤의 확인 요청은 묻지 않고 `false` 로 끝내는 문(순수 로직). 확인이 끝나면(답했든 실패했든) 다시 열린다.
 *
 * 문은 만든 쪽이 들고 다닌다. 모듈 전역 하나를 두면, 확인창이 열린 채 그 화면이 사라질 때 답이 영영 오지 않아(확인창
 * 라이브러리는 Root 가 언마운트되면 기다리던 호출을 끝내지 않고 버린다) 문이 닫힌 채 남고, 그 뒤로는 어느 화면의 확인도
 * 열리지 않는다. 화면마다 새 문을 만들면 버려진 호출은 사라진 화면의 문만 닫아 둔다.
 */
export function createConfirmGate(): (ask: () => Promise<boolean>) => Promise<boolean> {
  let isConfirming = false;

  return async (ask) => {
    if (isConfirming) return false;
    isConfirming = true;
    try {
      return await ask();
    } finally {
      isConfirming = false;
    }
  };
}
