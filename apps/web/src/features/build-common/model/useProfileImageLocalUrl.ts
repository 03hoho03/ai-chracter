import { useCallback, useEffect, useRef, useState } from "react";

import type { ProfileImageLocalEntry } from "./resolveProfileImageUrl";

/**
 * 이 기기에서 방금 올리거나 고른 대표 이미지의 표시 주소를 빌더 셸 높이에서 쥔다. 탭을 옮기면 탭 본문이
 * 언마운트되므로 이미지 칸 안에 두면 저장이 끝나기 전에 주소를 잃고, 미리보기 카드도 같은 값을 읽을 수 없다.
 * 브라우저 사본(objectURL)은 이 훅이 만들고 이 훅이 해제한다 — 칸이 만들고 칸 언마운트 때 해제하면 셸이 쥔
 * 주소가 탭 전환 순간 무효가 되어 카드가 깨진 이미지가 된다.
 */
export function useProfileImageLocalUrl() {
  const [local, setLocal] = useState<ProfileImageLocalEntry | undefined>(undefined);
  const heldObjectUrlRef = useRef<string | null>(null);
  // 기억 요청마다(그리고 언마운트 때) 하나씩 올린다. 뒤늦게 끝난 사본 받기는 자기 번호가 아직 최신인지로
  // 버릴지 정한다. 언마운트를 별도 플래그 대신 번호 올리기로 표시하므로, StrictMode 의 개발용
  // 마운트→정리→마운트가 "언마운트됨" 상태를 남기지 않는다(정리 시점엔 받는 중인 사본이 없다).
  const generationRef = useRef(0);

  const holdObjectUrl = useCallback((next: string | null) => {
    if (heldObjectUrlRef.current !== null) URL.revokeObjectURL(heldObjectUrlRef.current);
    heldObjectUrlRef.current = next;
  }, []);

  useEffect(
    () => () => {
      generationRef.current += 1;
      // 정리 시점에 쥐고 있는 사본을 해제해야 하므로 ref 를 그때 읽는다.
      if (heldObjectUrlRef.current !== null) URL.revokeObjectURL(heldObjectUrlRef.current);
      heldObjectUrlRef.current = null;
      // 개발 중 Fast Refresh 는 정리를 돌리면서 상태는 남긴다. 방금 해제한 사본 주소가 상태에 남아 깨진
      // 이미지가 되지 않도록 비운다. 진짜 언마운트에선 버려질 상태라 무해하고, StrictMode 의 첫 정리 시점엔
      // 이미 비어 있다.
      setLocal(undefined);
    },
    [],
  );

  // 해제는 setState 갱신 함수 밖(핸들러 본문)에서 한다 — StrictMode 가 갱신 함수를 두 번 불러 두 번째 호출이
  // 방금 만든 사본까지 해제할 수 있다.
  const rememberUploadedFile = useCallback(
    (assetId: string, file: File) => {
      generationRef.current += 1;
      const url = URL.createObjectURL(file);
      holdObjectUrl(url);
      setLocal({ assetId, url, canExpire: false });
    },
    [holdObjectUrl],
  );

  const rememberPickedImage = useCallback(
    (assetId: string, imageUrl: string) => {
      const generation = ++generationRef.current;
      holdObjectUrl(null);
      setLocal({ assetId, url: imageUrl, canExpire: true });

      // 고른 그림의 서명 주소는 만료되므로 뒤에서 브라우저 사본으로 바꿔 둔다. `no-store` 인 이유: 피커 그리드의
      // `<img>` 가 같은 주소를 CORS 없이 캐시해 뒀다면, 저장소 응답에 `Vary: Origin` 이 없을 때 그 캐시가 이
      // fetch 에 재사용돼 CORS 로 실패할 수 있다. 실패하면 서명 주소를 만료되는 주소로 표시한 채 둔다 — 이 값은
      // 셸이 빌더를 떠날 때까지 쥐므로 만료 뒤에도 남을 수 있고, 그래서 같은 자산의 서버 주소가 오면 표시 쪽에서
      // 그 주소에 자리를 내준다.
      fetch(imageUrl, { cache: "no-store" })
        .then((response) => (response.ok ? response.blob() : null))
        .then((blob) => {
          if (blob === null || generation !== generationRef.current) return;
          const url = URL.createObjectURL(blob);
          holdObjectUrl(url);
          setLocal({ assetId, url, canExpire: false });
        })
        .catch(() => undefined);
    },
    [holdObjectUrl],
  );

  return { local, rememberUploadedFile, rememberPickedImage };
}
