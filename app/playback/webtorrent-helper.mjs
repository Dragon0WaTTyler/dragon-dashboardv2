import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import readline from "node:readline";
import WebTorrent from "webtorrent";

const MIN_MEDIA_BYTES = 50 * 1024 * 1024;
const HEAD_PREFETCH_BYTES = 8 * 1024 * 1024;
const TAIL_PREFETCH_BYTES = 1024 * 1024;
const METADATA_TIMEOUT_MS = 30000;
const DIRECT_MEDIA_EXTENSIONS = [".mp4", ".m4v", ".webm"];
const TRANSCODE_MEDIA_EXTENSIONS = [".mkv", ".mov", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg"];

const episodeMatches = (fileName, target = {}) => {
  const season = Number(target.season || 0);
  const episode = Number(target.episode || 0);
  if (!season || !episode) return false;
  const normalized = String(fileName || "");
  const seasonValue = String(season).padStart(2, "0");
  const episodeValue = String(episode).padStart(2, "0");
  const patterns = [
    new RegExp(`(^|[^a-z0-9])s0*${season}e0*${episode}([^a-z0-9]|$)`, "i"),
    new RegExp(`(^|[^a-z0-9])${seasonValue}x${episodeValue}([^a-z0-9]|$)`, "i"),
    new RegExp(`(^|[^a-z0-9])0*${season}x0*${episode}([^a-z0-9]|$)`, "i"),
    new RegExp(`season[ ._-]*0*${season}.*episode[ ._-]*0*${episode}`, "i"),
  ];
  return patterns.some((pattern) => pattern.test(normalized));
};

export const chooseMedia = (files, minimumBytes = MIN_MEDIA_BYTES, target = {}) => {
  const candidates = files.filter((file) => {
    const name = String(file.name || "").toLowerCase();
    const extension = path.extname(name);
    return [...DIRECT_MEDIA_EXTENSIONS, ...TRANSCODE_MEDIA_EXTENSIONS].includes(extension)
      && Number(file.length || 0) >= minimumBytes
      && !/(^|[._ -])(sample|trailer)([._ -]|$)/i.test(name);
  });
  const needsExactEpisode = Boolean(Number(target.season || 0) && Number(target.episode || 0));
  const exactEpisode = candidates.filter((file) => episodeMatches(file.name, target));
  const ranked = needsExactEpisode ? exactEpisode : candidates;
  ranked.sort((left, right) => {
    const leftExtension = path.extname(String(left.name || "").toLowerCase());
    const rightExtension = path.extname(String(right.name || "").toLowerCase());
    const leftRank = DIRECT_MEDIA_EXTENSIONS.includes(leftExtension)
      ? 0
      : TRANSCODE_MEDIA_EXTENSIONS.includes(leftExtension)
        ? 1
        : 2;
    const rightRank = DIRECT_MEDIA_EXTENSIONS.includes(rightExtension)
      ? 0
      : TRANSCODE_MEDIA_EXTENSIONS.includes(rightExtension)
        ? 1
        : 2;
    return leftRank - rightRank || right.length - left.length;
  });
  return ranked[0] || null;
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

export const createLoopbackServer = (client, origin, secret = crypto.randomBytes(32).toString("hex")) => {
  const server = client.createServer({
    origin,
    hostname: "127.0.0.1",
    pathname: `/dragon-stream/${secret}`,
  });
  const serveWebTorrentRequest = server.onRequest.bind(server);
  server.onRequest = (request, callback) => {
    serveWebTorrentRequest(request, (result) => {
      const requestedRange = String(request.headers.range || "");
      if (requestedRange && (result.status !== 206 || requestedRange.includes(","))) {
        const total = Number(result.headers["Content-Length"] || 0);
        result.status = 416;
        result.headers["Content-Range"] = `bytes */${total}`;
        result.headers["Content-Length"] = "0";
        result.body = false;
      }
      callback(result);
    });
  };
  const serveRequest = server.wrapRequest.bind(server);
  server.wrapRequest = (request, response) => {
    if (request.headers.origin !== origin) {
      response.writeHead(403, {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Security-Policy": "default-src 'none'",
      });
      response.end("Forbidden");
      return;
    }
    serveRequest(request, response);
  };
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.server.once("error", onError);
    server.listen(0, "127.0.0.1", () => {
      server.server.off("error", onError);
      resolve(server);
    });
  });
};

export const resolveTorrentSession = async (client, cacheKey, torrentInput, options) => {
  const existingTorrent = await client.get(cacheKey);
  return existingTorrent || client.add(torrentInput, options);
};

export const buildStreamUrl = (address, media) => {
  if (!address || typeof address === "string") throw new Error("Playback server did not bind");
  const streamPath = String(media?.streamURL || "").replace(/\\/g, "/");
  return `http://127.0.0.1:${address.port}${streamPath}`;
};

const consumeWindow = async (session, start, end, kind) => {
  if (!session.file || end < start) return;
  let received = 0;
  try {
    const stream = session.file.createReadStream({ start, end });
    for await (const chunk of stream) {
      received += chunk.length;
      if (kind === "head") session.headBytes = received;
      else session.tailBytes = received;
    }
    if (kind === "head") session.headReady = true;
    else session.tailReady = true;
  } catch (error) {
    if (!session.torrent?.destroyed) {
      session.warning = String(error?.message || error || "Prefetch failed");
    }
  }
};

export const runRuntime = () => {
  const client = new WebTorrent();
  const sessions = new Map();
  let server = null;
  let allowedOrigin = "";

  const send = (id, response = {}) => {
    process.stdout.write(`${JSON.stringify({ id, ...response })}\n`);
  };

  const ensureServer = async (origin) => {
    if (server) {
      if (origin !== allowedOrigin) throw new Error("Playback origin changed unexpectedly");
      return server;
    }
    allowedOrigin = origin;
    server = await createLoopbackServer(client, origin);
    return server;
  };

  const payload = (session) => {
    const totalBytes = Number(session.file?.length || 0);
    const downloadedBytes = Number(session.file?.downloaded || 0);
    const headTarget = Math.min(HEAD_PREFETCH_BYTES, totalBytes);
    const bufferPercent = headTarget
      ? Math.min(100, Math.round((session.headBytes / headTarget) * 100))
      : 0;
    return {
      sessionId: session.id,
      fileName: String(session.file?.name || ""),
      totalBytes,
      downloadedBytes,
      fileProgress: Number(session.file?.progress || 0),
      bufferPercent,
      peers: Number(session.torrent?.numPeers || 0),
      downloadSpeed: Number(session.torrent?.downloadSpeed || 0),
      complete: Boolean(session.file?.done),
      directStream: Boolean(session.file && session.streamUrl),
      streamUrl: session.streamUrl || "",
      headReady: session.headReady,
      tailReady: session.tailReady,
      timings: session.timings,
      warning: session.warning || "",
      error: session.error || "",
    };
  };

  const start = async (message) => {
    const startedAt = Date.now();
    const cacheRoot = path.resolve(String(message.cacheRoot || ""));
    const root = path.resolve(String(message.root || ""));
    const cacheKey = String(message.cacheKey || "").toLowerCase();
    if (!cacheRoot || !root.startsWith(`${cacheRoot}${path.sep}`)) {
      throw new Error("Unsafe playback cache path");
    }
    fs.mkdirSync(root, { recursive: true });
    let torrentInput = String(message.magnet || "");
    if (message.torrentFile) {
      const torrentFile = path.resolve(String(message.torrentFile));
      if (!torrentFile.startsWith(`${cacheRoot}${path.sep}`)) {
        throw new Error("Unsafe torrent metadata path");
      }
      torrentInput = fs.readFileSync(torrentFile);
    } else if (!torrentInput.startsWith("magnet:?")) {
      throw new Error("Invalid magnet URI");
    }

    const torrent = await resolveTorrentSession(client, cacheKey, torrentInput, {
      path: root,
      strategy: "sequential",
      deselect: true,
      destroyStoreOnDestroy: false,
    });
    const session = {
      id: String(message.sessionId),
      root,
      torrent,
      file: null,
      streamUrl: "",
      headBytes: 0,
      tailBytes: 0,
      headReady: false,
      tailReady: false,
      warning: "",
      error: "",
      timings: { metadata_ms: null, first_peer_ms: null, stream_ready_ms: null },
    };
    sessions.set(session.id, session);
    torrent.on("wire", () => {
      if (session.timings.first_peer_ms === null) {
        session.timings.first_peer_ms = Date.now() - startedAt;
      }
    });
    torrent.on("warning", (error) => {
      session.warning = String(error?.message || error || "");
    });
    torrent.on("error", (error) => {
      session.error = String(error?.message || error || "");
    });
    await waitFor(
      () => Boolean(torrent.files?.length),
      METADATA_TIMEOUT_MS,
      "Torrent metadata timed out",
    );
    if (torrent.infoHash !== cacheKey) {
      throw new Error("Torrent metadata does not match the selected magnet");
    }
    session.timings.metadata_ms = Date.now() - startedAt;
    const target = {
      season: Number(message.season || 0),
      episode: Number(message.episode || 0),
    };
    const media = chooseMedia(torrent.files, MIN_MEDIA_BYTES, target);
    if (!media) {
      throw new Error(target.season && target.episode
        ? `No video file matching S${String(target.season).padStart(2, "0")}E${String(target.episode).padStart(2, "0")} was found in this torrent`
        : "No large video file was found in this torrent");
    }
    torrent.files.forEach((file) => file.deselect());
    session.file = media;
    const streamServer = await ensureServer(String(message.origin || ""));
    const address = streamServer.address();
    session.streamUrl = buildStreamUrl(address, media);
    session.timings.stream_ready_ms = Date.now() - startedAt;

    const headEnd = Math.min(media.length - 1, HEAD_PREFETCH_BYTES - 1);
    void consumeWindow(session, 0, headEnd, "head");
    if (/\.(mp4|m4v)$/i.test(media.name) && media.length > TAIL_PREFETCH_BYTES) {
      void consumeWindow(
        session,
        Math.max(0, media.length - TAIL_PREFETCH_BYTES),
        media.length - 1,
        "tail",
      );
    } else {
      session.tailReady = true;
    }
    return payload(session);
  };

  const close = async (sessionId) => {
    const session = sessions.get(sessionId);
    if (!session) return;
    sessions.delete(sessionId);
    if ([...sessions.values()].some((candidate) => candidate.torrent === session.torrent)) return;
    await new Promise((resolve) => session.torrent.destroy({ destroyStore: false }, resolve));
  };

  const handle = async (message) => {
    const command = String(message.command || "");
    if (command === "start") return start(message);
    if (command === "status") {
      const session = sessions.get(String(message.sessionId));
      if (!session) throw new Error("Playback session was not found");
      return payload(session);
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

  client.on("error", (error) => {
    process.stderr.write(`${String(error?.stack || error?.message || error)}\n`);
  });
  const shutdown = async () => {
    await Promise.all([...sessions.keys()].map(close));
    client.destroy(() => process.exit(0));
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
  return { client, sessions };
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runRuntime();
}
