// Rate limiting for /api/generate.
//
// Uses Upstash Redis when it's configured (env vars present) so limits are
// shared across all serverless instances. Without it, falls back to a
// best-effort in-memory limiter (per warm instance only) so local dev and a
// not-yet-configured deployment still get *some* protection.
//
// Fixed-window counters (per-IP daily, per-IP burst, global daily) via plain
// INCR/EXPIRE — no @upstash/ratelimit dependency needed.

import crypto from 'node:crypto';

const PER_IP_DAILY = num(process.env.RATELIMIT_PER_IP_DAILY, 15);
const GLOBAL_DAILY = num(process.env.RATELIMIT_GLOBAL_DAILY, 300);
const PER_IP_BURST = num(process.env.RATELIMIT_PER_IP_BURST, 5); // per 60s
const BURST_WINDOW_MS = 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

function num(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
}

function todayKey() {
  return new Date().toISOString().slice(0, 10); // UTC yyyy-mm-dd
}

export function clientIp(req) {
  const xff = req.headers['x-forwarded-for'];
  const raw =
    (typeof xff === 'string' && xff.split(',')[0].trim()) ||
    req.headers['x-real-ip'] ||
    req.socket?.remoteAddress ||
    'unknown';
  // Store a hash, never the raw IP.
  return crypto.createHash('sha256').update(String(raw)).digest('hex').slice(0, 16);
}

/* ------------------------------- Upstash path ------------------------------ */

let redis = null;
try {
  const url =
    process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL || '';
  const token =
    process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN || '';
  if (url && token) {
    const { Redis } = await import('@upstash/redis');
    redis = new Redis({ url, token });
  }
} catch (err) {
  console.error('ratelimit: Upstash init failed, using in-memory fallback:', err);
  redis = null;
}

export const usingRedis = Boolean(redis);

async function checkWithRedis(ipHash) {
  const day = todayKey();
  const ipDayKey = `cac:gen:ip:${ipHash}:${day}`;
  const ipBurstKey = `cac:gen:burst:${ipHash}`;
  const globalKey = `cac:gen:global:${day}`;

  const pipe = redis.multi();
  pipe.incr(ipDayKey);
  pipe.expire(ipDayKey, 60 * 60 * 24 + 60);
  pipe.incr(ipBurstKey);
  pipe.expire(ipBurstKey, 60);
  pipe.incr(globalKey);
  pipe.expire(globalKey, 60 * 60 * 24 + 60);
  const [ipDay, , ipBurst, , globalCount] = await pipe.exec();

  if (ipBurst > PER_IP_BURST) {
    return deny('burst', 60, 'Slow down a moment, then try again.');
  }
  if (ipDay > PER_IP_DAILY) {
    return deny('ip-daily', secondsUntilUtcMidnight(),
      `Daily limit reached (${PER_IP_DAILY} recipes per day). Try again tomorrow.`);
  }
  if (globalCount > GLOBAL_DAILY) {
    return deny('global-daily', secondsUntilUtcMidnight(),
      'This demo has hit its shared daily limit. Please check back tomorrow.');
  }
  return { ok: true, remaining: Math.max(0, PER_IP_DAILY - ipDay) };
}

/* ----------------------------- In-memory path ---------------------------- */

const memHits = new Map(); // ipHash -> number[] (timestamps, last 24h)
let memGlobal = { day: todayKey(), count: 0 };

function checkInMemory(ipHash) {
  const now = Date.now();

  if (memGlobal.day !== todayKey()) memGlobal = { day: todayKey(), count: 0 };
  memGlobal.count += 1;
  if (memGlobal.count > GLOBAL_DAILY) {
    return deny('global-daily', secondsUntilUtcMidnight(),
      'This demo has hit its shared daily limit. Please check back tomorrow.');
  }

  // Keep the map from growing without bound across many distinct IPs.
  if (memHits.size > 5000) memHits.clear();

  const hits = (memHits.get(ipHash) || []).filter((t) => now - t < DAY_MS);
  hits.push(now);
  memHits.set(ipHash, hits);

  const burst = hits.filter((t) => now - t < BURST_WINDOW_MS).length;
  if (burst > PER_IP_BURST) {
    return deny('burst', 60, 'Slow down a moment, then try again.');
  }
  if (hits.length > PER_IP_DAILY) {
    return deny('ip-daily', secondsUntilUtcMidnight(),
      `Daily limit reached (${PER_IP_DAILY} recipes per day). Try again tomorrow.`);
  }
  return { ok: true, remaining: Math.max(0, PER_IP_DAILY - hits.length) };
}

/* -------------------------------- helpers ------------------------------- */

function deny(scope, retryAfterSec, message) {
  return { ok: false, status: 429, scope, retryAfterSec, error: message };
}

function secondsUntilUtcMidnight() {
  const now = new Date();
  const midnight = new Date(now);
  midnight.setUTCHours(24, 0, 0, 0);
  return Math.ceil((midnight - now) / 1000);
}

/**
 * @returns {Promise<{ok:true, remaining:number} | {ok:false, status:number, scope:string, retryAfterSec:number, error:string}>}
 */
export async function checkRateLimit(req) {
  const ipHash = clientIp(req);
  try {
    return redis ? await checkWithRedis(ipHash) : checkInMemory(ipHash);
  } catch (err) {
    // Infra hiccup (Redis unreachable): fail open so the demo keeps working.
    console.error('ratelimit: check failed, allowing request:', err);
    return { ok: true, remaining: -1 };
  }
}
