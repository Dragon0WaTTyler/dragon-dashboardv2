import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import WebTorrent from "webtorrent";

const client = new WebTorrent();
const sessions = new Map();
const MIN_MEDIA_BYTES = 50 * 1024 * 1024;
const TAIL_BYTES = 2 * 1024 * 1024;

const send = (id, payload = {}) => {
  process.stdout.write(`${JSON.stringify({ id, ...payload })}\n`);
};

const safeName = (value) => String(value || "video").replace(/[^a-zA-Z0-9._-]+/g, "_");

const chooseMedia = (files) => {
  const candidates = files.filter((file) => {
    const name = String(file.name || "").toLowerCase();
    const extension = path.extname(name);
    return [".mp4", ".mkv", ".m4v", ".webm"].includes(extension)
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

const startMaterializer = (session, file) => {
  fs.mkdirSync(session.root, { recursive: true });
  const extension = path.extname(file.name).toLowerCase() || ".mp4";
  session.filePath = path.join(session.root, `${safeName(session.id)}${extension}`);
  session.fileName = path.basename(file.name);
  session.totalBytes = file.length;
  session.sequentialBytes = 0;
  session.tailStart = Math.max(0, file.length - TAIL_BYTES);
  session.tailReady = false;
  session.complete = false;
  session.error = "";

  const descriptor = fs.openSync(session.filePath, "w");
  fs.ftruncateSync(descriptor, file.length);
  fs.closeSync(descriptor);

  const sequential = file.createReadStream();
  const destination = fs.createWriteStream(session.filePath, { flags: "r+", start: 0 });
  session.destination = destination;
  sequential.on("error", (error) => { session.error = String(error.message || error); });
  destination.on("error", (error) => { session.error = String(error.message || error); });
  destination.on("finish", () => {
    session.sequentialBytes = file.length;
    session.complete = true;
  });
  sequential.pipe(destination);

  if (session.tailStart > 0) {
    const tail = file.createReadStream({ start: session.tailStart, end: file.length - 1 });
    const tailDestination = fs.createWriteStream(session.filePath, {
      flags: "r+",
      start: session.tailStart,
    });
    tail.on("error", (error) => { session.error = String(error.message || error); });
    tailDestination.on("error", (error) => { session.error = String(error.message || error); });
    tailDestination.on("finish", () => { session.tailReady = true; });
    tail.pipe(tailDestination);
  } else {
    session.tailReady = true;
  }
};

const sessionPayload = (session) => ({
  sessionId: session.id,
  fileName: session.fileName,
  filePath: session.filePath,
  totalBytes: session.totalBytes || 0,
  sequentialBytes: Math.min(
    Number(session.destination?.bytesWritten || session.sequentialBytes || 0),
    session.totalBytes || 0,
  ),
  tailStart: session.tailStart || 0,
  tailReady: Boolean(session.tailReady),
  complete: Boolean(session.complete),
  peers: Number(session.torrent?.numPeers || 0),
  downloadSpeed: Number(session.torrent?.downloadSpeed || 0),
  error: session.error || "",
});

const start = async (message) => {
  const root = path.resolve(String(message.root || ""));
  fs.mkdirSync(root, { recursive: true });
  const session = { id: String(message.sessionId), root, torrent: null };
  sessions.set(session.id, session);
  let torrentInput = String(message.magnet || "");
  if (message.torrentFile) {
    const torrentFile = path.resolve(String(message.torrentFile));
    if (!torrentFile.startsWith(`${root}${path.sep}`)) throw new Error("Unsafe torrent file path");
    torrentInput = fs.readFileSync(torrentFile);
  } else if (!torrentInput.startsWith("magnet:?")) {
    throw new Error("Invalid magnet URI");
  }
  const torrent = await new Promise((resolve, reject) => {
    const item = client.add(torrentInput, {
      path: path.join(root, "pieces"),
      strategy: "sequential",
      deselect: true,
      destroyStoreOnDestroy: false,
    }, resolve);
    session.torrent = item;
    const timer = setTimeout(() => reject(new Error("Torrent metadata timed out")), 30000);
    item.once("ready", () => clearTimeout(timer));
    item.once("error", (error) => { clearTimeout(timer); reject(error); });
  });
  session.torrent = torrent;
  const media = chooseMedia(torrent.files);
  if (!media) throw new Error("No supported movie file was found in this torrent");
  torrent.files.forEach((file) => file.deselect());
  media.select(10);
  startMaterializer(session, media);
  return sessionPayload(session);
};

const close = async (sessionId) => {
  const session = sessions.get(sessionId);
  if (!session) return;
  sessions.delete(sessionId);
  if (session.torrent) {
    await new Promise((resolve) => session.torrent.destroy({ destroyStore: true }, resolve));
  }
};

const handle = async (message) => {
  const command = String(message.command || "");
  if (command === "start") return start(message);
  if (command === "status") {
    const session = sessions.get(String(message.sessionId));
    if (!session) throw new Error("Playback session was not found");
    return sessionPayload(session);
  }
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

const shutdown = async () => {
  await Promise.all([...sessions.keys()].map(close));
  client.destroy(() => process.exit(0));
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
