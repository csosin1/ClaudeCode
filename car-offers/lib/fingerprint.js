/**
 * Fingerprint profile generator.
 *
 * Picks a realistic Windows 10 Chrome profile per session. Everything the
 * stealth init script needs (screen, hw concurrency, UA-CH values, canvas
 * noise seed) is derived once here so it stays internally consistent —
 * a bot-detection red flag is, for example, 1920x1080 viewport with a
 * laptop-class hw concurrency but a gaming-rig UA.
 */

// Realistic consumer Windows 10 laptop/desktop profiles. Each one is a
// coherent machine — resolution + dpr + hw concurrency + gpu match what
// a real shopper's PC would report. Distribution loosely weighted to
// the most common first.
const PROFILES = [
  {
    // Common 15" laptop (HP/Dell/Lenovo business-class)
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    dpr: 1,
    hardwareConcurrency: 8,
    deviceMemory: 8,
    gpu: {
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'Intel Inc.',
      unmaskedRenderer: 'Intel(R) UHD Graphics 620',
    },
  },
  {
    // Mid-range 14" laptop (1536x864 is the most common reported desktop res globally)
    screen: { width: 1536, height: 864, availWidth: 1536, availHeight: 824 },
    dpr: 1.25,
    hardwareConcurrency: 8,
    deviceMemory: 8,
    gpu: {
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'Intel Inc.',
      unmaskedRenderer: 'Intel(R) Iris(R) Xe Graphics',
    },
  },
  {
    // Older business laptop
    screen: { width: 1366, height: 768, availWidth: 1366, availHeight: 728 },
    dpr: 1,
    hardwareConcurrency: 4,
    deviceMemory: 8,
    gpu: {
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) HD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'Intel Inc.',
      unmaskedRenderer: 'Intel(R) HD Graphics 620',
    },
  },
  {
    // Desktop w/ discrete GPU
    screen: { width: 1440, height: 900, availWidth: 1440, availHeight: 860 },
    dpr: 1,
    hardwareConcurrency: 12,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (NVIDIA)',
      renderer: 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'NVIDIA Corporation',
      unmaskedRenderer: 'NVIDIA GeForce GTX 1650',
    },
  },
];

/** Deterministic 32-bit hash — used as a canvas/audio noise seed. */
function hashSeed(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * Given a session id (e.g. proxy sticky session), pick a coherent
 * fingerprint profile deterministically. Same session → same fingerprint
 * across runs; different session → different fingerprint. This is what
 * we want: the persistent Chrome profile's identity should not change
 * mid-life, but a rotation does get a new machine.
 */
function pickProfile(sessionId) {
  const idx = hashSeed(String(sessionId || 'default')) % PROFILES.length;
  const base = PROFILES[idx];
  const seed = hashSeed(String(sessionId || 'default') + ':noise');

  // Chrome version — pin to a current stable. Bump periodically.
  const chromeMajor = 131;
  const chromeFull = '131.0.6778.205';

  const userAgent = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeMajor}.0.0.0 Safari/537.36`;

  const secChUa = `"Chromium";v="${chromeMajor}", "Google Chrome";v="${chromeMajor}", "Not-A.Brand";v="24"`;
  const secChUaFullVersionList = `"Chromium";v="${chromeFull}", "Google Chrome";v="${chromeFull}", "Not-A.Brand";v="24.0.0.0"`;

  return {
    ...base,
    seed,
    userAgent,
    chromeMajor,
    chromeFull,
    platform: 'Win32',
    oscpu: undefined, // Chrome never exposes navigator.oscpu (Firefox does); keeping undefined matches real Chrome
    secChUa,
    secChUaFullVersionList,
    secChUaPlatform: '"Windows"',
    secChUaPlatformVersion: '"15.0.0"',
    acceptLanguage: 'en-US,en;q=0.9',
    languages: ['en-US', 'en'],
    locale: 'en-US',
    timezone: 'America/New_York',
  };
}

module.exports = { pickProfile, hashSeed, PROFILES };
