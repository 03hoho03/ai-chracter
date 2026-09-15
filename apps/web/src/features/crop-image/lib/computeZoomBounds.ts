/**
 * 크롭 줌 범위 계산(image-crop-goal-prompt.md IC-7).
 *
 * minZoom은 항상 1이다 — `react-easy-crop`의 `getCropSize`가 zoom=1에서 크롭 박스를
 * 미디어(= 원본과 같은 비율로 축소된 렌더 크기) 안에 맞춰 넣으므로(`Math.min(media, container)`,
 * `objectFit:'contain'`이라 미디어가 항상 컨테이너 이하) 여백이 생길 수 없다.
 *
 * maxZoom은 크롭 결과가 목표 해상도(maxEdge) 아래로 내려가지 않는 배율이다. zoom=1의 크롭 사각형은
 * 원본 안에 들어가는 최대 `aspect` 사각형이고(컨테이너 크기와 무관), 크롭 사각형은 zoom에 반비례해
 * 줄어들므로 maxZoom = longEdge(zoom=1) / maxEdge다.
 */
export function computeZoomBounds(params: {
  naturalWidth: number;
  naturalHeight: number;
  aspect: number;
  maxEdge: number;
}): { minZoom: number; maxZoom: number } {
  const { naturalWidth, naturalHeight, aspect, maxEdge } = params;

  const { width, height } =
    naturalWidth / naturalHeight > aspect
      ? { width: naturalHeight * aspect, height: naturalHeight }
      : { width: naturalWidth, height: naturalWidth / aspect };

  const longEdge = Math.max(width, height);

  // 원본이 목표 해상도보다 작으면 계산값이 1 밑으로 내려간다 — 하한(1)으로 클램프하지 않으면
  // maxZoom < minZoom이 되어 슬라이더가 죽는다.
  const maxZoom = Math.max(1, longEdge / maxEdge);

  return { minZoom: 1, maxZoom };
}
