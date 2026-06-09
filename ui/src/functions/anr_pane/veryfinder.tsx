import { useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Pill,
} from "@/design-system";
import type { VeryfinderOverlay, VeryfinderPost } from "@/lib/veryfinder";
import type { VeryfinderRunState } from "./_types";
import {
  clampTweetSample,
  formatDateTime,
  formatInt,
  formatPct,
  formatSignedInt,
  providerLabel,
  veryfinderTone,
} from "./formatters";
import {
  analysisListRowStyle,
  analysisListStyle,
  analysisMutedStyle,
  analysisQueryStyle,
  analysisTextStyle,
  tweetDrawerStyle,
  tweetDrawerToggleStyle,
  tweetListStyle,
  tweetRowMetaStyle,
  tweetRowStyle,
  tweetSearchControlStyle,
  tweetSearchGoButtonStyle,
  tweetSearchInputStyle,
  tweetSearchIntentStyle,
  tweetSearchLabelStyle,
  tweetTagRowStyle,
  tweetTextStyle,
  twoColumnAnalysisGridStyle,
  veryfinderLoadBarStyle,
  veryfinderLoadKickerStyle,
  veryfinderLoadMetaStyle,
  veryfinderLoadMeterStyle,
  veryfinderLoadShellStyle,
  veryfinderLoadTitleStyle,
  veryfinderLoadTopStyle,
  veryfinderStepCardStyle,
  veryfinderStepGridStyle,
} from "./styles";
import { DistributionBlock } from "./cards";
import { StatGrid } from "./tables";

export function VeryfinderAnalysisCard({
  enabled,
  overlay,
  state,
  error,
  minTweets,
  minTweetsInput,
  recommendedTweets,
  source,
  startedAt,
  updatedAt,
  liveRefreshCount,
  onMinTweetsInputChange,
  onTweetSearch,
}: {
  enabled: boolean;
  overlay: VeryfinderOverlay | null;
  state: VeryfinderRunState;
  error: string | null;
  minTweets: number;
  minTweetsInput: string;
  recommendedTweets: number;
  source: string;
  startedAt: string | null;
  updatedAt: string | null;
  liveRefreshCount: number;
  onMinTweetsInputChange: (value: string) => void;
  onTweetSearch: () => void;
}) {
  const requestedTweets = clampTweetSample(minTweetsInput);
  const [tweetDrawerOpen, setTweetDrawerOpen] = useState(false);
  const posts = overlay?.posts ?? overlay?.analyzed_posts ?? [];
  const refreshing = state === "refreshing";
  return (
    <Card>
      <CardHeader
        trailing={
          <div className="u-flex u-gap-6 u-flex-wrap u-justify-end">
            <Pill tone={enabled ? veryfinderTone(overlay?.tone) : "muted"} variant="soft">{enabled ? state : "off"}</Pill>
            {enabled ? <Pill tone={refreshing ? "warn" : "positive"} variant="soft" withDot={!refreshing}>rolling · 30s</Pill> : null}
            {overlay?.fixture_mode ? <Pill tone="warn" variant="soft">fixture</Pill> : null}
            {overlay?.fallback_mode ? <Pill tone="warn" variant="soft">{providerLabel(overlay.fallback_mode)}</Pill> : null}
          </div>
        }
      >
        Veryfinder Analysis
      </CardHeader>
      <CardBody>
        <div style={tweetSearchControlStyle}>
          <label style={tweetSearchLabelStyle}>
            <span>Min tweets</span>
            <input
              type="number"
              min={1}
              step={1}
              value={minTweetsInput}
              disabled={!enabled || state === "loading"}
              onChange={(event) => onMinTweetsInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onTweetSearch();
              }}
              style={tweetSearchInputStyle}
            />
          </label>
          <button
            type="button"
            className="btn"
            onClick={onTweetSearch}
            disabled={!enabled || state === "loading"}
            title="Apply rolling tweet window and refresh now"
            style={tweetSearchGoButtonStyle}
          >
            GO
          </button>
          <span style={tweetSearchIntentStyle}>rolling window · newest {formatInt(requestedTweets)} tweets</span>
          <span style={analysisMutedStyle}>applied · {formatInt(minTweets)}</span>
          <span style={analysisMutedStyle}>efficient default · {formatInt(recommendedTweets)}</span>
          <span style={analysisMutedStyle}>auto refresh · 30s</span>
        </div>
        {!enabled ? (
          <p style={analysisTextStyle}>Veryfinder overlay is disabled for this ANR run.</p>
        ) : state === "loading" ? (
          <VeryfinderSearchLoadScreen
            target={minTweets}
            requestedInput={requestedTweets}
            source={source}
            startedAt={startedAt}
            previous={overlay}
            postsOpen={tweetDrawerOpen}
            onTogglePosts={() => setTweetDrawerOpen((open) => !open)}
          />
        ) : error ? (
          <p style={analysisTextStyle}>{error}</p>
        ) : overlay ? (
          <div className="u-grid-gap-12">
            <StatGrid
              items={[
                ["Dominant view", overlay.dominant_view?.display ?? "—"],
                ["Confidence", formatPct(Number(overlay.dominant_view?.score ?? 0) * 100)],
                ["Social score", formatSignedInt(overlay.social_score)],
                ["Min tweet target", formatInt(minTweets)],
                ["Rolling window", `${formatInt(overlay.rolling_window_size ?? minTweets)} newest`],
                ["Requested sample", formatInt(overlay.requested_sample ?? minTweets)],
                ["Unique accounts", formatInt(overlay.unique_accounts)],
                ["Collected posts", formatInt(overlay.collected_posts)],
                ["Last refresh", updatedAt ? formatDateTime(updatedAt) : "—"],
                ["Live refreshes", formatInt(liveRefreshCount)],
                ["Tweet estimate", formatInt(overlay.tweet_count_estimate)],
                ["Source", providerLabel(overlay.source)],
                ["Engine", overlay.engine ?? "—"],
              ]}
            />
            {Number(overlay.collected_posts ?? 0) < Number(overlay.requested_sample ?? minTweets) ? (
              <p style={analysisTextStyle}>
                Source capacity note: this rolling window requested {formatInt(overlay.requested_sample ?? minTweets)} tweets;
                {overlay.fixture_mode ? " fixture mode contains 12 demo posts." : ` the source returned ${formatInt(overlay.collected_posts)} posts.`}
              </p>
            ) : null}
            <div style={twoColumnAnalysisGridStyle}>
              <DistributionBlock title="View distribution" distribution={overlay.view_distribution} />
              <DistributionBlock title="Mood distribution" distribution={overlay.mood_distribution} />
              <DistributionBlock title="Action distribution" distribution={overlay.action_distribution} />
              <DistributionBlock title="Sentiment distribution" distribution={overlay.sentiment_distribution} />
            </div>
            <p style={analysisTextStyle}>{overlay.meaning}</p>
            <p title={overlay.query} style={analysisQueryStyle}>Query: {overlay.query ?? "—"}</p>
            <TweetEvidenceDrawer
              posts={posts}
              open={tweetDrawerOpen}
              onToggle={() => setTweetDrawerOpen((open) => !open)}
              title={`Rolling tweet window · ${formatInt(posts.length)} newest`}
            />
            {overlay.model_notes?.length ? (
              <div style={analysisListStyle}>
                {overlay.model_notes.slice(0, 5).map((note) => (
                  <div key={note} style={analysisListRowStyle}>
                    <strong>note</strong>
                    <span>{note}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <p style={analysisTextStyle}>Veryfinder returned no analysis payload.</p>
        )}
      </CardBody>
    </Card>
  );
}

export function VeryfinderSearchLoadScreen({
  target,
  requestedInput,
  source,
  startedAt,
  previous,
  postsOpen,
  onTogglePosts,
}: {
  target: number;
  requestedInput: number;
  source: string;
  startedAt: string | null;
  previous: VeryfinderOverlay | null;
  postsOpen: boolean;
  onTogglePosts: () => void;
}) {
  const posts = previous?.posts ?? previous?.analyzed_posts ?? [];
  return (
    <div style={veryfinderLoadShellStyle}>
      <div style={veryfinderLoadTopStyle}>
        {/*
          A11Y: the live region is SCOPED to this transient status/progress
          node only. The static step cards below sit OUTSIDE it, so the 30s
          Veryfinder poll re-announces the status message, not the whole shell.
        */}
        <div role="status" aria-live="polite">
          <div style={veryfinderLoadKickerStyle}>Veryfinder live search</div>
          <div style={veryfinderLoadTitleStyle}>Searching social reaction</div>
          <p style={analysisTextStyle}>
            Requesting {formatInt(target)} tweets from {providerLabel(source)}; current input target is {formatInt(requestedInput)}.
            The pipeline is fetching posts, deduping unique accounts, then scoring sentiment, mood, action, and market view.
          </p>
        </div>
        <div style={veryfinderLoadMeterStyle}>
          <span style={{ ...veryfinderLoadBarStyle, height: 18 }} />
          <span style={{ ...veryfinderLoadBarStyle, height: 34 }} />
          <span style={{ ...veryfinderLoadBarStyle, height: 26 }} />
        </div>
      </div>
      <div style={veryfinderStepGridStyle}>
        {[
          ["1", "Search", "X/RSS query dispatch"],
          ["2", "Dedupe", "one vote per account"],
          ["3", "Score", "sentiment/action/view"],
          ["4", "Render", "evidence drawer + alert"],
        ].map(([index, label, value]) => (
          <div key={label} style={veryfinderStepCardStyle}>
            <strong>{index}</strong>
            <span>{label}</span>
            <small>{value}</small>
          </div>
        ))}
      </div>
      <div style={veryfinderLoadMetaStyle}>
        <span>started · {startedAt ? formatDateTime(startedAt) : "now"}</span>
        <span>previous collected · {formatInt(previous?.collected_posts)}</span>
        <span>previous requested · {formatInt(previous?.requested_sample)}</span>
      </div>
      {posts.length ? (
        <TweetEvidenceDrawer
          posts={posts}
          open={postsOpen}
          onToggle={onTogglePosts}
          title={`Last tweet evidence while search runs · ${formatInt(posts.length)}`}
        />
      ) : null}
    </div>
  );
}

export function TweetEvidenceDrawer({
  posts,
  open,
  onToggle,
  title,
}: {
  posts: VeryfinderPost[];
  open: boolean;
  onToggle: () => void;
  title: string;
}) {
  return (
    <div style={tweetDrawerStyle}>
      <button
        type="button"
        className="btn btn--ghost"
        onClick={onToggle}
        style={tweetDrawerToggleStyle}
      >
        <span>{open ? "-" : "+"}</span>
        <strong>{title}</strong>
        <small>{open ? "hide" : "inspect"}</small>
      </button>
      {open ? (
        posts.length ? (
          <div style={tweetListStyle}>
            {posts.map((post, index) => (
              <TweetEvidenceRow key={post.id || `${post.username}-${index}`} post={post} />
            ))}
          </div>
        ) : (
          <p style={analysisTextStyle}>No tweet evidence was returned by the source for this run.</p>
        )
      ) : null}
    </div>
  );
}

function TweetEvidenceRow({ post }: { post: VeryfinderPost }) {
  const handle = post.username ? `@${post.username}` : post.author_id ?? "unknown";
  const label = post.view?.label || post.sentiment?.label || "unclassified";
  return (
    <div style={tweetRowStyle}>
      <div style={tweetRowMetaStyle}>
        <strong>{handle}</strong>
        <span>{label.replaceAll("_", " ")}</span>
        <span>rel {formatPct(Number(post.relevance ?? 0) * 100)}</span>
        <span>eng {formatInt(post.engagement)}</span>
        <span>{post.created_at ? formatDateTime(post.created_at) : "time —"}</span>
        {post.url ? (
          <a href={post.url} target="_blank" rel="noopener noreferrer" className="u-text-accent">
            open ↗
          </a>
        ) : null}
      </div>
      <p style={tweetTextStyle}>{post.text || "Text unavailable."}</p>
      <div style={tweetTagRowStyle}>
        <span>sentiment · {post.sentiment?.label ?? "—"}</span>
        <span>action · {post.action?.label ?? "—"}</span>
        <span>mood · {post.mood?.label ?? "—"}</span>
      </div>
    </div>
  );
}
