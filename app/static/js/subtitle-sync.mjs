const SCHEMA_VERSION = 1;
const MIN_ANCHOR_SEPARATION_MS = 120_000;
const MIN_SCALE = 0.5;
const MAX_SCALE = 2;

export class SubtitleSyncError extends Error {}

const finite = (value) => Number.isFinite(Number(value));
const asNumber = (value) => Number(value);

const cleanSegment = (segment) => {
  const subtitleStartMs = asNumber(segment?.subtitle_start_ms);
  const scale = asNumber(segment?.scale);
  const offsetMs = asNumber(segment?.offset_ms);
  if (!finite(subtitleStartMs) || subtitleStartMs < 0 || !finite(scale) || !finite(offsetMs)) return null;
  if (scale < MIN_SCALE || scale > MAX_SCALE) return null;
  return { subtitle_start_ms: Math.round(subtitleStartMs), scale, offset_ms: Math.round(offsetMs) };
};

const orderedSegments = (segments) => {
  const byStart = new Map();
  (Array.isArray(segments) ? segments : []).forEach((segment) => {
    const cleaned = cleanSegment(segment);
    if (cleaned) byStart.set(cleaned.subtitle_start_ms, cleaned);
  });
  if (!byStart.has(0)) byStart.set(0, { subtitle_start_ms: 0, scale: 1, offset_ms: 0 });
  return Array.from(byStart.values()).sort((left, right) => left.subtitle_start_ms - right.subtitle_start_ms);
};

const cleanAnchor = (anchor) => {
  const subtitleMs = asNumber(anchor?.subtitle_ms);
  const videoMs = asNumber(anchor?.video_ms);
  if (!finite(subtitleMs) || subtitleMs < 0 || !finite(videoMs) || videoMs < 0) return null;
  return { subtitle_ms: Math.round(subtitleMs), video_ms: Math.round(videoMs) };
};

export const defaultSubtitleSyncProfile = () => ({
  schema_version: SCHEMA_VERSION,
  mode: "constant",
  anchors: [],
  segments: [{ subtitle_start_ms: 0, scale: 1, offset_ms: 0 }],
  updated_at: new Date().toISOString(),
  revision: 0,
});

export const normalizeSubtitleSyncProfile = (raw) => {
  const base = defaultSubtitleSyncProfile();
  if (!raw || typeof raw !== "object") return base;
  const segments = orderedSegments(raw.segments);
  const anchors = (Array.isArray(raw.anchors) ? raw.anchors : []).map(cleanAnchor).filter(Boolean).slice(-2);
  const inferredMode = segments.length > 1 ? "segmented" : anchors.length > 1 ? "linear" : "constant";
  return {
    schema_version: SCHEMA_VERSION,
    mode: ["constant", "linear", "segmented"].includes(raw.mode) ? raw.mode : inferredMode,
    anchors,
    segments,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : base.updated_at,
    revision: Math.max(0, Math.round(asNumber(raw.revision) || 0)),
  };
};

const updated = (profile, patch) => ({
  ...normalizeSubtitleSyncProfile(profile),
  ...patch,
  schema_version: SCHEMA_VERSION,
  updated_at: new Date().toISOString(),
  revision: normalizeSubtitleSyncProfile(profile).revision + 1,
});

export const segmentForSubtitleTime = (originalMs, profile) => {
  const value = asNumber(originalMs);
  if (!finite(value)) throw new SubtitleSyncError("Subtitle time is invalid.");
  return orderedSegments(normalizeSubtitleSyncProfile(profile).segments)
    .filter((segment) => segment.subtitle_start_ms <= value)
    .at(-1) || { subtitle_start_ms: 0, scale: 1, offset_ms: 0 };
};

export const transformSubtitleTime = (originalMs, profile) => {
  const value = asNumber(originalMs);
  const segment = segmentForSubtitleTime(value, profile);
  const corrected = segment.scale * value + segment.offset_ms;
  if (!finite(corrected)) throw new SubtitleSyncError("Subtitle timing calculation is invalid.");
  return Math.round(corrected);
};

export const transformSubtitleCue = (cue, profile) => {
  const startMs = asNumber(cue?.start_ms);
  const endMs = asNumber(cue?.end_ms);
  if (!finite(startMs) || !finite(endMs) || endMs <= startMs) {
    throw new SubtitleSyncError("Subtitle cue timing is invalid.");
  }
  const start = Math.max(0, transformSubtitleTime(startMs, profile));
  const end = Math.max(0, transformSubtitleTime(endMs, profile));
  const scale = Math.abs(segmentForSubtitleTime(startMs, profile).scale);
  const safeDuration = Math.max(1, Math.round((endMs - startMs) * scale));
  return { start_ms: start, end_ms: end > start ? end : start + safeDuration };
};

export const nearestSubtitleCueIndexAt = (cues, videoMs) => {
  const target = asNumber(videoMs);
  if (!finite(target)) throw new SubtitleSyncError("Playback time is invalid.");
  let closestIndex = -1;
  let closestDistance = Number.POSITIVE_INFINITY;
  (Array.isArray(cues) ? cues : []).forEach((cue, index) => {
    const startMs = asNumber(cue?.start_ms);
    if (!finite(startMs)) return;
    const distance = Math.abs(startMs - target);
    if (distance < closestDistance) {
      closestIndex = index;
      closestDistance = distance;
    }
  });
  return closestIndex;
};

export const calibrateOnePoint = (subtitleMs, videoMs, profile = defaultSubtitleSyncProfile()) => {
  const anchor = cleanAnchor({ subtitle_ms: subtitleMs, video_ms: videoMs });
  if (!anchor) throw new SubtitleSyncError("Choose a valid subtitle line before synchronizing.");
  return updated(profile, {
    mode: "constant",
    anchors: [anchor],
    segments: [{ subtitle_start_ms: 0, scale: 1, offset_ms: anchor.video_ms - anchor.subtitle_ms }],
  });
};

export const calibrateTwoPoints = (first, second, profile = defaultSubtitleSyncProfile()) => {
  const anchorA = cleanAnchor(first);
  const anchorB = cleanAnchor(second);
  if (!anchorA || !anchorB) throw new SubtitleSyncError("Both synchronization points must be valid.");
  const subtitleDelta = anchorB.subtitle_ms - anchorA.subtitle_ms;
  const videoDelta = anchorB.video_ms - anchorA.video_ms;
  if (subtitleDelta < MIN_ANCHOR_SEPARATION_MS || videoDelta <= 0) {
    throw new SubtitleSyncError("The second point must be at least two minutes from the first.");
  }
  const scale = videoDelta / subtitleDelta;
  if (!finite(scale) || scale < MIN_SCALE || scale > MAX_SCALE) {
    throw new SubtitleSyncError("Those points produce an unsafe subtitle rate. Keep the last valid sync.");
  }
  const offsetMs = anchorA.video_ms - scale * anchorA.subtitle_ms;
  if (!finite(offsetMs)) throw new SubtitleSyncError("Those points produce invalid subtitle timing.");
  return updated(profile, {
    mode: "linear",
    anchors: [anchorA, anchorB],
    segments: [{ subtitle_start_ms: 0, scale, offset_ms: Math.round(offsetMs) }],
  });
};

export const resyncSubtitleFromHere = (subtitleMs, videoMs, profile = defaultSubtitleSyncProfile()) => {
  const anchor = cleanAnchor({ subtitle_ms: subtitleMs, video_ms: videoMs });
  if (!anchor) throw new SubtitleSyncError("Choose a valid subtitle line before resynchronizing.");
  const normalized = normalizeSubtitleSyncProfile(profile);
  const previous = segmentForSubtitleTime(anchor.subtitle_ms, normalized);
  const next = {
    subtitle_start_ms: anchor.subtitle_ms,
    scale: previous.scale,
    offset_ms: Math.round(anchor.video_ms - previous.scale * anchor.subtitle_ms),
  };
  return updated(normalized, {
    mode: "segmented",
    segments: orderedSegments([
      ...normalized.segments.filter((segment) => segment.subtitle_start_ms < anchor.subtitle_ms),
      next,
    ]),
  });
};

export const adjustSubtitleSync = (profile, deltaMs) => {
  if (!finite(deltaMs)) throw new SubtitleSyncError("Subtitle adjustment is invalid.");
  const normalized = normalizeSubtitleSyncProfile(profile);
  return updated(normalized, {
    segments: normalized.segments.map((segment) => ({ ...segment, offset_ms: Math.round(segment.offset_ms + asNumber(deltaMs)) })),
    anchors: normalized.anchors.map((anchor) => ({ ...anchor, video_ms: Math.round(anchor.video_ms + asNumber(deltaMs)) })),
  });
};

export const subtitleSyncSummary = (profile) => {
  const normalized = normalizeSubtitleSyncProfile(profile);
  const first = normalized.segments[0];
  if (normalized.mode === "segmented") return `Synced in ${normalized.segments.length} segments`;
  if (normalized.mode === "linear") return `Synced using 2 points · ${first.scale.toFixed(4)}×`;
  if (!first.offset_ms) return "Original timing";
  const sign = first.offset_ms > 0 ? "+" : "−";
  const total = Math.abs(first.offset_ms);
  const minutes = Math.floor(total / 60000);
  const seconds = ((total % 60000) / 1000).toFixed(1).padStart(4, "0");
  return `Offset ${sign}${minutes}:${seconds}`;
};

export const subtitleSyncStorageKey = ({ movieId, sourceId, subtitleId }) => (
  `dragon:subtitle-sync:v1:${encodeURIComponent(movieId)}:${encodeURIComponent(sourceId)}:${encodeURIComponent(subtitleId)}`
);

export const subtitleSyncLimits = {
  minAnchorSeparationMs: MIN_ANCHOR_SEPARATION_MS,
  minScale: MIN_SCALE,
  maxScale: MAX_SCALE,
};
