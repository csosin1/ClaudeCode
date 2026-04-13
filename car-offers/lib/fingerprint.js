/**
 * Fingerprint profile generator.
 *
 * Picks a realistic Chrome profile per session. Everything the stealth init
 * script needs (screen, hw concurrency, UA-CH values, canvas noise seed) is
 * derived once here so it stays internally consistent — a bot-detection red
 * flag is, for example, 1920x1080 viewport with a laptop-class hw concurrency
 * but a gaming-rig UA.
 *
 * Panel model: each consumer has a FIXED fingerprint_profile_id assigned in
 * the consumers table, picked via pickProfileByIndex(idx). PROFILES is
 * expanded to >=12 coherent machines spanning Win10 laptops + desktops and
 * Mac laptops + desktops so 12 consumers each get a distinctive device
 * fingerprint.
 */

// Windows 10/11 laptops (4)
const WIN_LAPTOPS = [
  {
    label: 'Win10 HP business laptop 1366x768',
    os: 'Windows',
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
    label: 'Win10 Dell Latitude 1440x900',
    os: 'Windows',
    screen: { width: 1440, height: 900, availWidth: 1440, availHeight: 860 },
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
    label: 'Win11 Lenovo Iris Xe 1536x864',
    os: 'Windows',
    screen: { width: 1536, height: 864, availWidth: 1536, availHeight: 824 },
    dpr: 1.25,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'Intel Inc.',
      unmaskedRenderer: 'Intel(R) Iris(R) Xe Graphics',
    },
  },
  {
    label: 'Win10 ASUS gaming laptop 1920x1080 GTX 1650',
    os: 'Windows',
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    dpr: 1,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (NVIDIA)',
      renderer: 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'NVIDIA Corporation',
      unmaskedRenderer: 'NVIDIA GeForce GTX 1650',
    },
  },
];

// Windows 10/11 desktops (4)
const WIN_DESKTOPS = [
  {
    label: 'Win11 desktop RTX 3060 1920x1080',
    os: 'Windows',
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    dpr: 1,
    hardwareConcurrency: 12,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (NVIDIA)',
      renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'NVIDIA Corporation',
      unmaskedRenderer: 'NVIDIA GeForce RTX 3060',
    },
  },
  {
    label: 'Win10 desktop AMD RX 6600 2560x1440',
    os: 'Windows',
    screen: { width: 2560, height: 1440, availWidth: 2560, availHeight: 1400 },
    dpr: 1,
    hardwareConcurrency: 12,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (AMD)',
      renderer: 'ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'ATI Technologies Inc.',
      unmaskedRenderer: 'AMD Radeon RX 6600',
    },
  },
  {
    label: 'Win11 office desktop Intel UHD 770 1920x1080',
    os: 'Windows',
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    dpr: 1,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (Intel)',
      renderer: 'ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'Intel Inc.',
      unmaskedRenderer: 'Intel(R) UHD Graphics 770',
    },
  },
  {
    label: 'Win10 desktop RTX 2060 1920x1080',
    os: 'Windows',
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    dpr: 1,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (NVIDIA)',
      renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)',
      unmaskedVendor: 'NVIDIA Corporation',
      unmaskedRenderer: 'NVIDIA GeForce RTX 2060',
    },
  },
];

// Mac laptops (2) — MacBook Air M1/M2
const MAC_LAPTOPS = [
  {
    label: 'MacBook Air M1 13" 1440x900',
    os: 'macOS',
    screen: { width: 1440, height: 900, availWidth: 1440, availHeight: 875 },
    dpr: 2,
    hardwareConcurrency: 8,
    deviceMemory: 8,
    gpu: {
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)',
      unmaskedVendor: 'Apple Inc.',
      unmaskedRenderer: 'Apple M1',
    },
  },
  {
    label: 'MacBook Air M2 13" 1470x956',
    os: 'macOS',
    screen: { width: 1470, height: 956, availWidth: 1470, availHeight: 931 },
    dpr: 2,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)',
      unmaskedVendor: 'Apple Inc.',
      unmaskedRenderer: 'Apple M2',
    },
  },
];

// Mac desktops (2)
const MAC_DESKTOPS = [
  {
    label: 'iMac 27" M1 2560x1440',
    os: 'macOS',
    screen: { width: 2560, height: 1440, availWidth: 2560, availHeight: 1415 },
    dpr: 2,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)',
      unmaskedVendor: 'Apple Inc.',
      unmaskedRenderer: 'Apple M1',
    },
  },
  {
    label: 'Mac Mini M2 1920x1080',
    os: 'macOS',
    screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1055 },
    dpr: 2,
    hardwareConcurrency: 8,
    deviceMemory: 16,
    gpu: {
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)',
      unmaskedVendor: 'Apple Inc.',
      unmaskedRenderer: 'Apple M2',
    },
  },
];

const PROFILES = [
  ...WIN_LAPTOPS,
  ...WIN_DESKTOPS,
  ...MAC_LAPTOPS,
  ...MAC_DESKTOPS,
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

// Chrome version — pin to a current stable. Bump periodically.
const CHROME_MAJOR = 131;
const CHROME_FULL = '131.0.6778.205';

/** Derive OS-specific UA + client hints from the base profile. */
function _decorate(base, sessionId) {
  const seed = hashSeed(String(sessionId || 'default') + ':noise');

  let userAgent, platform, secChUaPlatform, secChUaPlatformVersion;
  if (base.os === 'macOS') {
    userAgent = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROME_MAJOR}.0.0.0 Safari/537.36`;
    platform = 'MacIntel';
    secChUaPlatform = '"macOS"';
    secChUaPlatformVersion = '"14.5.0"';
  } else {
    userAgent = `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROME_MAJOR}.0.0.0 Safari/537.36`;
    platform = 'Win32';
    secChUaPlatform = '"Windows"';
    secChUaPlatformVersion = '"15.0.0"';
  }

  const secChUa = `"Chromium";v="${CHROME_MAJOR}", "Google Chrome";v="${CHROME_MAJOR}", "Not-A.Brand";v="24"`;
  const secChUaFullVersionList = `"Chromium";v="${CHROME_FULL}", "Google Chrome";v="${CHROME_FULL}", "Not-A.Brand";v="24.0.0.0"`;

  return {
    ...base,
    seed,
    userAgent,
    chromeMajor: CHROME_MAJOR,
    chromeFull: CHROME_FULL,
    platform,
    oscpu: undefined,
    secChUa,
    secChUaFullVersionList,
    secChUaPlatform,
    secChUaPlatformVersion,
    acceptLanguage: 'en-US,en;q=0.9',
    languages: ['en-US', 'en'],
    locale: 'en-US',
    timezone: 'America/New_York',
  };
}

/**
 * Given a session id (e.g. proxy sticky session), pick a coherent fingerprint
 * profile deterministically. Same session -> same fingerprint across runs;
 * different session -> different fingerprint. Backward-compatible with
 * pre-panel callers that don't know their consumer ID.
 */
function pickProfile(sessionId) {
  const idx = hashSeed(String(sessionId || 'default')) % PROFILES.length;
  return _decorate(PROFILES[idx], sessionId);
}

/**
 * Direct profile selection by index, used by the panel consumers table.
 * Out-of-range indices wrap around so a bad DB entry never throws.
 */
function pickProfileByIndex(idx, sessionId) {
  const safeIdx = ((Number(idx) || 0) % PROFILES.length + PROFILES.length) % PROFILES.length;
  return _decorate(PROFILES[safeIdx], sessionId || `profile-${safeIdx}`);
}

module.exports = {
  pickProfile,
  pickProfileByIndex,
  hashSeed,
  PROFILES,
  CHROME_MAJOR,
  CHROME_FULL,
};
