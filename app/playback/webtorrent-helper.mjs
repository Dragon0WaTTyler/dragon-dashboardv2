import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import WebTorrent from "webtorrent";

const client = new WebTorrent();
const sessions = new Map();
const MIN_MEDIA_BYTES = 50 * 1024 * 1024;
const MAX_RANGE_BYTES = 512 * 1024;
const RANGE_TIMEOUT_MS = 45000;

const send = (id, payload = {}) => {
  process.stdout.write(`${JSON.stringify({ id, ...payload })}\n`);
};

const waitFor = (predicate, timeoutMs, message) => new Promise((resolve, reject) => {
  const deadline = Date.now() + timeoutMs;
  const check = () => {
    if (predicate()) return resolve();
    if (Date.now() >= deadline) return reject(new Error(message));
    setTimeout(check, 100);
  };
  check();
});

const chooseMedia = (files) => {
  const candidates = files.filter((file) => {
    const name = String(file.name || "").toLowerCase();
    const extension = path.extname(name);
    return [".mp4", ".m4v", ".webm"].includes(extension)
      && Number(file.length || 0) >= MIN_MEDIA_BYTES
      && !/(^|[._ -])(sample|trailer)([._ -]|$)/i.test(name);
  });
  candidates.sort((left, right) => {
    const leftRank = /\.(mp4|m4v)$/i.test(left.name) ? 0 : 1;
    const rightRank = /\.(mp4|m4v)$/i.test(right.name) ? 0 : 1;
    return leftRank - rightRank || right.length - left.length;
  });
  return candidates[0] || null;
};

const payload = (session) => ({
  sessionId: session.id,
  fileName: String(session.file?.name || ""),
  totalBytes: Number(session.file?.length || 0),
  peers: Number(session.torrent?.numPeers || 0),
  downloadSpeed: Number(session.torrent?.downloadSpeed || 0),
  complete: Boolean(session.torrent?.done),
  directStream: Boolean(session.file),
  warning: session.warning || "",
  error: session.error || "",
});

const start = async (message) => {
  const root = path.resolve(String(message.root || ""));
  fs.mkdirSync(root, { recursive: true });
  let torrentInput = String(message.magnet || "");
  if (message.torrentFile) {
    const torrentFile = path.resolve(String(message.torrentFile));
    if (!torrentFile.startsWith(`${root}${path.sep}`)) throw new Error("Unsafe torrent file path");
    torrentInput = fs.readFileSync(torrentFile);
  } else if (!torrentInput.startsWith("magnet:?")) {
    throw new Error("Invalid magnet URI");
  }

  const existingTorrent = await client.get(torrentInput);
  const torrent = existingTorrent || client.add(torrentInput, {
      path: path.join(root, "pieces"),
      strategy: "sequential",
      deselect: true,
      destroyStoreOnDestroy: false,
    });
  const session = {
    id: String(message.sessionId),
    root,
    torrent,
    file: null,
    warning: "",
    error: "",
  };
  sessions.set(session.id, session);
  torrent.on("warning", (error) => { session.warning = String(error?.message || error || ""); });
  torrent.on("error", (error) => { session.error = String(error?.message || error || ""); });
  await waitFor(
    () => Boolean(torrent.files?.length),
    30000,
    "Torrent metadata timed out",
  );
  const media = chooseMedia(torrent.files);
  if (!media) throw new Error("No browser-compatible MP4 file was found in this torrent");
  torrent.files.forEach((file) => file.deselect());
  session.file = media;
  return payload(session);
};

const readRange = async (message) => {
  const session = sessions.get(String(message.sessionId));
  if (!session?.file) throw new Error("Playback session was not found");
  const startByte = Number(message.start);
  const endByte = Number(message.end);
  if (!Number.isSafeInteger(startByte) || !Number.isSafeInteger(endByte)
      || startByte < 0 || endByte < startByte || endByte >= session.file.length) {
    throw new Error("Invalid playback range");
  }
  if (endByte - startByte + 1 > MAX_RANGE_BYTES) throw new Error("Playback range is too large");

  const data = await new Promise((resolve, reject) => {
    const chunks = [];
    let settled = false;
    const stream = session.file.createReadStream({ start: startByte, end: endByte });
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) {
        try { stream.destroy(); } catch (_error) { /* no-op */ }
        reject(error);
        return;
      }
      resolve(Buffer.concat(chunks));
    };
    const timer = setTimeout(
      () => finish(new Error("Torrent pieces timed out")),
      RANGE_TIMEOUT_MS,
    );
    stream.on("data", (chunk) => chunks.push(chunk));
    stream.once("end", () => finish());
    stream.once("error", (error) => finish(error));
  });
  const expected = endByte - startByte + 1;
  if (data.length !== expected) throw new Error("Torrent returned an incomplete byte range");
  return { data: data.toString("base64"), bytes: data.length };
};

const close = async (sessionId) => {
  const session = sessions.get(sessionId);
  if (!session) return;
  sessions.delete(sessionId);
  if ([...sessions.values()].some((candidate) => candidate.torrent === session.torrent)) return;
  await new Promise((resolve) => session.torrent.destroy({ destroyStore: true }, resolve));
};

const handle = async (message) => {
  const command = String(message.command || "");
  if (command === "start") return start(message);
  if (command === "status") {
    const session = sessions.get(String(message.sessionId));
    if (!session) throw new Error("Playback session was not found");
    return payload(session);
  }
  if (command === "read") return readRange(message);
  if (command === "close") {
    await close(String(message.sessionId));
    return { closed: true };
  }
  throw new Error("Unsupported runtime command");
};

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", async (line) => {
  let message;
  try {
    message = JSON.parse(line);
    send(message.id, { ok: true, result: await handle(message) });
  } catch (error) {
    send(message?.id || "unknown", {
      ok: false,
      error: String(error?.message || error || "WebTorrent runtime failed"),
    });
  }
});

client.on("error", (error) => {
  process.stderr.write(`${String(error?.stack || error?.message || error)}\n`);
});
const shutdown = async () => {
  await Promise.all([...sessions.keys()].map(close));
  client.destroy(() => process.exit(0));
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
