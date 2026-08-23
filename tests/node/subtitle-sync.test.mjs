import assert from "node:assert/strict";
import test from "node:test";

import {
  SubtitleSyncError,
  adjustSubtitleSync,
  calibrateOnePoint,
  calibrateTwoPoints,
  defaultSubtitleSyncProfile,
  nearestSubtitleCueIndexAt,
  resyncSubtitleFromHere,
  subtitleSyncStorageKey,
  transformSubtitleCue,
  transformSubtitleTime,
} from "../../app/static/js/subtitle-sync.mjs";

test("constant subtitle offsets preserve millisecond precision, including large and negative corrections", () => {
  const positive = calibrateOnePoint(100000, 105000);
  assert.equal(transformSubtitleTime(100000, positive), 105000);
  const negative = calibrateOnePoint(100000, 95000);
  assert.equal(transformSubtitleTime(100000, negative), 95000);
  const large = calibrateOnePoint(675000, 1122300);
  assert.equal(transformSubtitleTime(675000, large), 1122300);
  assert.equal(transformSubtitleTime(0, large), 447300);
});

test("two points derive one linear mapping for anchors and intermediate cues", () => {
  const profile = calibrateTwoPoints(
    { subtitle_ms: 600000, video_ms: 620000 },
    { subtitle_ms: 3600000, video_ms: 3665000 },
  );
  assert.equal(transformSubtitleTime(600000, profile), 620000);
  assert.equal(transformSubtitleTime(3600000, profile), 3665000);
  assert.equal(transformSubtitleTime(2100000, profile), 2142500);
});

test("invalid two-point calibration rejects malformed, close, and unreasonable anchors", () => {
  assert.throws(
    () => calibrateTwoPoints({ subtitle_ms: 600000, video_ms: 620000 }, { subtitle_ms: 600000, video_ms: 650000 }),
    SubtitleSyncError,
  );
  assert.throws(
    () => calibrateTwoPoints({ subtitle_ms: 600000, video_ms: 620000 }, { subtitle_ms: 650000, video_ms: 700000 }),
    SubtitleSyncError,
  );
  assert.throws(
    () => calibrateTwoPoints({ subtitle_ms: 600000, video_ms: 620000 }, { subtitle_ms: 3600000, video_ms: 9000000 }),
    SubtitleSyncError,
  );
  assert.throws(
    () => calibrateTwoPoints({ subtitle_ms: 3600000, video_ms: 3665000 }, { subtitle_ms: 600000, video_ms: 620000 }),
    SubtitleSyncError,
  );
  assert.throws(
    () => calibrateTwoPoints({ subtitle_ms: Number.NaN, video_ms: 620000 }, { subtitle_ms: 3600000, video_ms: 3665000 }),
    SubtitleSyncError,
  );
});

test("segmented sync changes only the requested later subtitle boundary", () => {
  const offset = calibrateOnePoint(0, 5000);
  const segmented = resyncSubtitleFromHere(1800000, 1920000, offset);
  assert.equal(transformSubtitleTime(1799999, segmented), 1804999);
  assert.equal(transformSubtitleTime(1800000, segmented), 1920000);
  assert.equal(transformSubtitleTime(2100000, segmented), 2220000);
});

test("fine tuning shifts all segments without rounding away 0.1 seconds", () => {
  const profile = adjustSubtitleSync(defaultSubtitleSyncProfile(), 100);
  assert.equal(transformSubtitleTime(100000, profile), 100100);
});

test("cue transformation clamps negative starts and preserves a valid duration", () => {
  const profile = calibrateOnePoint(1000, 0);
  assert.deepEqual(transformSubtitleCue({ start_ms: 1000, end_ms: 2500 }, profile), {
    start_ms: 0,
    end_ms: 1500,
  });
});

test("the cue selector follows corrected video time rather than original subtitle time", () => {
  const correctedCues = [
    { start_ms: 722400, end_ms: 724000 },
    { start_ms: 1410200, end_ms: 1411800 },
    { start_ms: 1413600, end_ms: 1415400 },
  ];
  assert.equal(nearestSubtitleCueIndexAt(correctedCues, 1410000), 1);
});

test("persistence keys isolate source and subtitle combinations", () => {
  const base = { movieId: "movie_1", sourceId: "source_a", subtitleId: "sha256-a" };
  assert.equal(subtitleSyncStorageKey(base), subtitleSyncStorageKey(base));
  assert.notEqual(subtitleSyncStorageKey(base), subtitleSyncStorageKey({ ...base, sourceId: "source_b" }));
  assert.notEqual(subtitleSyncStorageKey(base), subtitleSyncStorageKey({ ...base, subtitleId: "sha256-b" }));
});
