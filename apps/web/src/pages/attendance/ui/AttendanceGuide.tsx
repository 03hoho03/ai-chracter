import { useId } from "react";

/** 출석 규칙 안내. 첫 줄의 사용 기간은 공개 가격 응답의 값이다 — 웹에 숫자 사본을 두면 기간을 바꿀 때 이 줄만 거짓으로
 * 남는다. 같은 사실(지급분의 최소 사용 기간)을 클로버 충전 화면의 정책 문장도 말하므로 기간을 바꾸면 둘이 함께 바뀐다.
 * 가격 응답이 없으면(로그인 회원이 가격만 못 받은 경우) 그 줄을 뺀다. */
export function AttendanceGuide({ minValidDays }: { minValidDays: number | undefined }) {
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className="mt-2 flex flex-col gap-2">
      <h2 id={headingId} className="text-sm font-semibold text-foreground">
        알아 두세요
      </h2>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-sm break-keep text-muted-foreground marker:text-muted-foreground">
        {minValidDays !== undefined && <li>받은 클로버는 받은 날부터 {minValidDays}일 동안 쓸 수 있어요.</li>}
        <li>하루 한 번, 한국 시간 자정에 새로 받을 수 있어요.</li>
        <li>받지 않은 날은 진도가 늘지 않아요. 다음에 오면 이어서 받아요.</li>
        <li>출석 보상은 본인인증을 마친 회원만 받을 수 있어요.</li>
      </ul>
    </section>
  );
}
