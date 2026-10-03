import { Link } from "@tanstack/react-router";
import { Fragment } from "react";

import { STORY_FIELD_LABELS } from "@/features/build-story";
import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import { GUIDE_QUIET_LINK_CLASS } from "../config/guideStyles";
import { READ_TIMING_GROUPS, type StoryFieldMockups } from "../config/storyFieldMockups";
import { isStoryFieldKey } from "../model/mockupCaption";
import type { GuideAnchor } from "../model/toGuidePages";

type GuideReadTimingListProps = {
  topicId: CreationGuideTopicId;
  mockups: StoryFieldMockups;
  anchorOfKey: ReadonlyMap<string, GuideAnchor>;
  /** 이 목록을 이름 짓는 절 제목의 id. */
  labelledBy: string;
};

/**
 * "칸을 AI가 읽는 때" — 읽는 때마다 칸 이름을 모아 보인다. 표로 그리지 않는다(좁은 화면에서 가로 스크롤이 생긴다).
 * 그룹 머리를 제목 요소로 두지 않는 이유: 짧은 그룹 일곱 개가 연달아 제목이 되면 제목으로 훑는 낭독기 탐색이 시끄럽다.
 *
 * 칸 이름은 그 칸 블록으로 가는 링크다. 같은 표가 단계 페이지 목업 캡션도 만들어, 여기와 캡션이 다른 말을 할 수 없다.
 */
export function GuideReadTimingList({ topicId, mockups, anchorOfKey, labelledBy }: GuideReadTimingListProps) {
  return (
    <ul aria-labelledby={labelledBy} className="m-0 flex list-none flex-col gap-5 p-0">
      {READ_TIMING_GROUPS.map((group) => {
        const keys = Object.keys(mockups).filter(
          (key) => isStoryFieldKey(key) && mockups[key].readTiming === group.id && anchorOfKey.has(key),
        );
        return (
          <li key={group.id} className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold break-keep text-foreground">{group.title}</span>
            <span className="text-sm leading-relaxed break-keep text-muted-foreground">
              {keys.map((key, index) => {
                const anchor = anchorOfKey.get(key);
                if (!anchor || !isStoryFieldKey(key)) return null;
                return (
                  <Fragment key={key}>
                    {index > 0 && " · "}
                    <Link
                      to={GUIDE_STEP_ROUTES[topicId]}
                      params={{ step: anchor.stepId }}
                      hash={anchor.anchorId}
                      className={GUIDE_QUIET_LINK_CLASS}
                    >
                      {STORY_FIELD_LABELS[key].label}
                    </Link>
                  </Fragment>
                );
              })}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
