/**
 * 여러 번 불려도 한 번만 실행하고 그 결과를 모두가 나눠 갖는 래퍼(순수 로직).
 *
 * 초안 지연 생성(US-007)이 이걸 필요로 한다 — 자동저장은 연속 입력마다 트리거되고 상황별 이미지
 * 등록도 같은 초안을 요구하는데, `POST /contents`가 두 번 나가면 빈 초안이 하나 더 쌓인다. 첫 호출이
 * 아직 끝나지 않았어도 뒤따르는 호출은 같은 프라미스를 기다려야 하므로 "완료 여부"가 아니라
 * **진행 중인 프라미스**를 기억한다.
 *
 * 실패하면 기억을 지운다 — 네트워크 오류로 한 번 실패한 뒤 영영 만들 수 없게 되면 안 된다.
 */
export function runOnce<T>(run: () => Promise<T>): () => Promise<T> {
  let pending: Promise<T> | null = null;

  return () => {
    pending ??= run().catch((error: unknown) => {
      pending = null;
      throw error;
    });
    return pending;
  };
}
