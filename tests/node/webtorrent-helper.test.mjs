import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { after, before, test } from "node:test";
import WebTorrent from "webtorrent";

import {
  buildStreamUrl,
  chooseMedia,
  createLoopbackServer,
  resolveTorrentSession,
} from "../../app/playback/webtorrent-helper.mjs";

const ORIGIN = "http://127.0.0.1:5050";
const SECRET = "test-secret-path";
const CONTENT = Buffer.from("dragon-direct-range-stream-".repeat(4096));
let client;
let server;
let torrent;
let temporaryRoot;
let streamPath;

const seed = (target) => new Promise((resolve, reject) => {
  const onError = (error) => reject(error);
  client.once("error", onError);
  client.seed(target, { announce: [] }, (value) => {
    client.off("error", onError);
    resolve(value);
  });
});

const request = ({ method = "GET", range = "", requestPath = streamPath, host } = {}) => (
  new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback(value);
    };
    const address = server.address();
    const headers = {
      Origin: ORIGIN,
      Host: host || `127.0.0.1:${address.port}`,
      Connection: "close",
    };
    if (range) headers.Range = range;
    const call = http.request({
      hostname: "127.0.0.1",
      port: address.port,
      path: requestPath,
      method,
      headers,
      agent: false,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => finish(resolve, {
        status: response.statusCode,
        headers: response.headers,
        body: Buffer.concat(chunks),
      }));
    });
    const timer = setTimeout(() => {
      call.destroy();
      finish(reject, new Error("request timed out"));
    }, 3000);
    call.once("error", (error) => finish(reject, error));
    call.end();
  })
);

before(async () => {
  temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), "dragon-webtorrent-test-"));
  const moviePath = path.join(temporaryRoot, "fixture.mp4");
  await fs.writeFile(moviePath, CONTENT);
  client = new WebTorrent({ dht: false, tracker: false, lsd: false });
  torrent = await seed(moviePath);
  server = await createLoopbackServer(client, ORIGIN, SECRET);
  streamPath = torrent.files[0].streamURL;
});

after(async () => {
  server.sockets.forEach((socket) => socket.destroy());
  await new Promise((resolve) => server.destroy(resolve));
  await new Promise((resolve) => client.destroy(resolve));
  await fs.rm(temporaryRoot, { recursive: true, force: true });
});

test("serves GET, HEAD, prefix, suffix, and seek ranges directly", async () => {
  const head = await request({ method: "HEAD" });
  assert.equal(head.status, 200);
  assert.equal(Number(head.headers["content-length"]), CONTENT.length);
  assert.equal(head.body.length, 0);

  const prefix = await request({ range: "bytes=0-9" });
  assert.equal(prefix.status, 206);
  assert.equal(prefix.headers["content-range"], `bytes 0-9/${CONTENT.length}`);
  assert.deepEqual(prefix.body, CONTENT.subarray(0, 10));

  const seek = await request({ range: "bytes=2048-4095" });
  assert.equal(seek.status, 206);
  assert.deepEqual(seek.body, CONTENT.subarray(2048, 4096));

  const suffix = await request({ range: "bytes=-16" });
  assert.equal(suffix.status, 206);
  assert.deepEqual(suffix.body, CONTENT.subarray(-16));
});

test("rejects invalid ranges, missing secrets, wrong origins, and wrong hosts", async () => {
  const invalid = await request({ range: `bytes=${CONTENT.length + 1}-` });
  assert.equal(invalid.status, 416);

  await assert.rejects(request({ requestPath: streamPath.replace(SECRET, "wrong") }));

  await assert.rejects(request({ host: "evil.example" }));

  const originalOrigin = ORIGIN;
  const address = server.address();
  const denied = await new Promise((resolve, reject) => {
    const call = http.request({
      hostname: "127.0.0.1",
      port: address.port,
      path: streamPath,
      headers: {
        Origin: `${originalOrigin}.evil`,
        Host: `127.0.0.1:${address.port}`,
        Connection: "close",
      },
      agent: false,
    }, (response) => {
      response.resume();
      response.once("end", () => resolve(response.statusCode));
    });
    const timer = setTimeout(() => {
      call.destroy();
      reject(new Error("request timed out"));
    }, 3000);
    call.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    call.once("response", () => clearTimeout(timer));
    call.end();
  });
  assert.equal(denied, 403);
});

test("returns an available local range within the warm first-byte budget", async () => {
  await request({ range: "bytes=0-1023" });
  const started = performance.now();
  const response = await request({ range: "bytes=0-1023" });
  const elapsed = performance.now() - started;
  assert.equal(response.status, 206);
  assert.ok(elapsed < 250, `warm local first byte took ${elapsed.toFixed(1)}ms`);
});

test("awaits async client.get before falling back to add", async () => {
  const existingTorrent = { on() {}, files: [] };
  let addCalled = false;
  const fakeClient = {
    async get(infoHash) {
      assert.equal(infoHash, "cache-key");
      return existingTorrent;
    },
    add() {
      addCalled = true;
      return { on() {}, files: [] };
    },
  };

  const torrent = await resolveTorrentSession(fakeClient, "cache-key", "magnet:?xt=urn:btih:test", {
    path: "/tmp/example",
  });

  assert.equal(torrent, existingTorrent);
  assert.equal(addCalled, false);
});

test("normalizes Windows torrent paths before exposing stream URLs", () => {
  const url = buildStreamUrl(
    { port: 5055 },
    { streamURL: "/dragon-stream/secret/hash/Season Pack\\Episode 01.mp4" },
  );

  assert.equal(url, "http://127.0.0.1:5055/dragon-stream/secret/hash/Season Pack/Episode 01.mp4");
});

test("falls back to MKV when no direct MP4-style file exists", () => {
  const media = chooseMedia([
    { name: "The.Sopranos.S01E01.sample.mkv", length: 500_000_000 },
    { name: "The.Sopranos.S01E01.mkv", length: 4_000_000_000 },
    { name: "The.Sopranos.S01E01.txt", length: 1000 },
  ]);

  assert.equal(media?.name, "The.Sopranos.S01E01.mkv");
});

test("selects the requested episode from a season pack", () => {
  const media = chooseMedia([
    { name: "The.Sopranos.S01E02.1080p.mkv", length: 4_200_000_000 },
    { name: "The.Sopranos.S01E01.1080p.mkv", length: 3_800_000_000 },
    { name: "The.Sopranos.S01E03.1080p.mkv", length: 4_000_000_000 },
  ], undefined, { season: 1, episode: 1 });

  assert.equal(media?.name, "The.Sopranos.S01E01.1080p.mkv");
});

test("does not guess a different file when the requested episode is missing", () => {
  const media = chooseMedia([
    { name: "The.Sopranos.S01E02.1080p.mkv", length: 4_200_000_000 },
    { name: "The.Sopranos.S01E03.1080p.mkv", length: 4_000_000_000 },
  ], undefined, { season: 1, episode: 1 });

  assert.equal(media, null);
});
