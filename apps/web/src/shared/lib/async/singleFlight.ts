/** 한 번에 하나만 도는 비동기 실행기. 앞의 작업이 끝나기 전에 다시 부르면 작업을 부르지 않고 `undefined`로 끝난다.
 *
 * 확인 버튼을 같은 순간 두 번 누르면 두 번째 클릭은 뮤테이션의 `isPending`이 다시 그려지기 전에 들어와 요청이 둘 나간다 —
 * 그래서 렌더를 기다리지 않는 이 표시로 막는다. 컴포넌트는 `useState(createSingleFlight)`로 한 개를 만들어 쓴다. */
export function createSingleFlight() {
  let isRunning = false;
  return async function runExclusive<T>(task: () => Promise<T>): Promise<T | undefined> {
    if (isRunning) return undefined;
    isRunning = true;
    try {
      return await task();
    } finally {
      isRunning = false;
    }
  };
}
