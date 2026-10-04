import type { ReactNode } from "react";

type PageHeaderProps = {
  title: string;
  /** 보통 "목록으로" 링크. 타입 안전한 `Link` 는 호출부가 그린다. */
  back?: ReactNode;
  actions?: ReactNode;
};

/**
 * 화면 머리. 제목과 동작은 늘 줄바꿈할 수 있어 좁은 화면에서는 동작이 제목 아래 줄로 내려간다(제목이 세로로
 * 꺾이지 않는다). 쿼리 밖에 두어 로딩·오류에도 남긴다.
 *
 * 뷰포트 `sm:` 를 쓰는 이유: `lg` 이상에서 셸 본문은 늘 640px 를 넘고 `lg` 미만에서는 본문이 곧 뷰포트라,
 * 이 머리가 놓이는 셸 본문 열에서는 `sm` 판정이 본문 폭 판정과 어긋나는 구간이 없다.
 */
export function PageHeader({ title, back, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-3">
      {back}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="min-w-0 break-keep text-2xl font-bold tracking-tight text-foreground">{title}</h1>
        {!!actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}
