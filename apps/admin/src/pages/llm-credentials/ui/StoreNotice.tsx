import { STORE_MISSING_TEXT } from "../model/labels";
import { STORE_NOTICE_ID } from "./elementIds";

/** 저장소 설정이 없다는 안내. 오류가 아니라 설정 상태라 틴트가 아니라 윤곽이고, 화면을 막지 않는다 — 끄기·삭제 같은 되돌리기 동작은
 * 저장소 없이도 된다. 키가 필요한 버튼들이 이 문장을 막힌 이유로 가리킨다. */
export function StoreNotice() {
  return (
    <div role="status" className="rounded-lg border border-border p-3">
      <p id={STORE_NOTICE_ID} className="max-w-prose break-keep text-sm text-foreground">
        {STORE_MISSING_TEXT}
      </p>
    </div>
  );
}
