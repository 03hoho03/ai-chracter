import type { LocalBuildElsewhereError } from "@/shared/api/labMode";
import { Notice } from "@/shared/ui/Notice";

/**
 * 루프백 밖 출처에서 연 로컬 빌드의 안내 — 목록·상세가 같은 안내를 쓴다. 다시 시도해도 같아 행동을 두지 않는다. 측정 서버를 띄우라는
 * 안내는 틀린 안내다(보는 사람 컴퓨터에는 측정 서버가 없다).
 */
export function LocalBuildElsewhereNotice({ error }: { error: LocalBuildElsewhereError }) {
  return (
    <Notice title="이 화면은 로컬 빌드다">
      <p className="text-ink">{error.message}</p>
    </Notice>
  );
}
