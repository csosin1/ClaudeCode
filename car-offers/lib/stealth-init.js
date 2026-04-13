/**
 * Build the stealth init script that Chromium executes on every frame
 * (main + iframes) before any page JS runs. Returns a string of JS.
 *
 * All values are injected from Node via `profile`, so the same session
 * gets the same fingerprint across pages. The script runs inside the
 * page context; Playwright's `addInitScript` applies to all frames in
 * the context, including cross-origin iframes (e.g. Turnstile widget).
 */
function buildStealthInitScript(profile) {
  const profileJson = JSON.stringify({
    seed: profile.seed,
    screen: profile.screen,
    dpr: profile.dpr,
    hardwareConcurrency: profile.hardwareConcurrency,
    deviceMemory: profile.deviceMemory,
    gpu: profile.gpu,
    userAgent: profile.userAgent,
    chromeMajor: profile.chromeMajor,
    chromeFull: profile.chromeFull,
    platform: profile.platform,
    secChUa: profile.secChUa,
    secChUaFullVersionList: profile.secChUaFullVersionList,
    secChUaPlatform: profile.secChUaPlatform,
    secChUaPlatformVersion: profile.secChUaPlatformVersion,
    languages: profile.languages,
    locale: profile.locale,
    timezone: profile.timezone,
  });

  // Use a plain function body string. We wrap it in an IIFE so it runs
  // immediately on every frame. No template interpolation happens inside
  // the body other than the profileJson injection below, which is a safe
  // JSON literal.
  return `(() => {
  "use strict";
  window.__stealthApplied = true;
  const P = ${profileJson};

  // Seeded PRNG (mulberry32) — stable per session for canvas/audio noise.
  let _rngState = P.seed >>> 0;
  const rng = () => {
    _rngState = (_rngState + 0x6D2B79F5) >>> 0;
    let t = _rngState;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  // Helper: try to override a navigator property at both prototype AND
  // instance level (some properties are already shadowed on the instance).
  const defNav = (name, value) => {
    try { Object.defineProperty(Navigator.prototype, name, { get: () => value, configurable: true }); } catch(e){}
    try { Object.defineProperty(navigator, name, { get: () => value, configurable: true }); } catch(e){}
  };

  // ---- 1. webdriver ----
  try { Object.defineProperty(Navigator.prototype, "webdriver", { get: () => false, configurable: true }); } catch(e){}
  try { Object.defineProperty(navigator, "webdriver", { get: () => false, configurable: true }); } catch(e){}

  // ---- 2. plugins / mimeTypes ----
  try {
    const pdf = { type: "application/pdf", suffixes: "pdf", description: "" };
    const mimes = [pdf, { type: "text/pdf", suffixes: "pdf", description: "" }];
    const plugins = [
      { name: "PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
      { name: "Chrome PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
      { name: "Chromium PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
      { name: "Microsoft Edge PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format" },
      { name: "WebKit built-in PDF", filename: "internal-pdf-viewer", description: "Portable Document Format" },
    ];
    defNav("plugins", plugins);
    defNav("mimeTypes", mimes);
  } catch(e){}

  // ---- 3. languages / language ----
  defNav("languages", P.languages);
  defNav("language", P.languages[0]);

  // ---- 4. platform / hw / vendor / maxTouchPoints / productSub ----
  defNav("platform", P.platform);
  defNav("hardwareConcurrency", P.hardwareConcurrency);
  defNav("deviceMemory", P.deviceMemory);
  defNav("maxTouchPoints", 0);
  defNav("vendor", "Google Inc.");
  defNav("productSub", "20030107");

  // ---- 5. userAgentData ----
  try {
    const brands = [
      { brand: "Chromium", version: String(P.chromeMajor) },
      { brand: "Google Chrome", version: String(P.chromeMajor) },
      { brand: "Not-A.Brand", version: "24" },
    ];
    const fullVersionList = [
      { brand: "Chromium", version: P.chromeFull },
      { brand: "Google Chrome", version: P.chromeFull },
      { brand: "Not-A.Brand", version: "24.0.0.0" },
    ];
    const uad = {
      brands, mobile: false, platform: "Windows",
      getHighEntropyValues: (hints) => {
        const out = { brands, mobile: false, platform: "Windows" };
        if (!hints) return Promise.resolve(out);
        if (hints.includes("architecture")) out.architecture = "x86";
        if (hints.includes("bitness")) out.bitness = "64";
        if (hints.includes("model")) out.model = "";
        if (hints.includes("platformVersion")) out.platformVersion = "15.0.0";
        if (hints.includes("uaFullVersion")) out.uaFullVersion = P.chromeFull;
        if (hints.includes("fullVersionList")) out.fullVersionList = fullVersionList;
        if (hints.includes("wow64")) out.wow64 = false;
        return Promise.resolve(out);
      },
      toJSON: () => ({ brands, mobile: false, platform: "Windows" }),
    };
    defNav("userAgentData", uad);
  } catch(e){}

  // ---- 6. window.chrome (realistic shape) ----
  try {
    const startE = (Date.now() - 1000 * (30 + Math.floor(rng() * 300))) / 1000;
    const commitE = startE + 0.08 + rng() * 0.15;
    const finishE = commitE + 0.12 + rng() * 0.4;
    const loadEventE = finishE + 0.05 + rng() * 0.2;
    const loadTimes = () => ({
      requestTime: startE,
      startLoadTime: startE,
      commitLoadTime: commitE,
      finishDocumentLoadTime: finishE,
      finishLoadTime: loadEventE,
      firstPaintTime: finishE + 0.05,
      firstPaintAfterLoadTime: 0,
      navigationType: "Other",
      wasFetchedViaSpdy: true,
      wasNpnNegotiated: true,
      npnNegotiatedProtocol: "h2",
      wasAlternateProtocolAvailable: false,
      connectionInfo: "h2",
    });
    const csi = () => ({
      onloadT: Date.now(),
      pageT: Math.floor(performance.now()),
      startE: Math.floor(startE * 1000),
      tran: 15,
    });
    const chromeObj = {
      app: {
        isInstalled: false,
        InstallState: { DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed" },
        RunningState: { CANNOT_RUN: "cannot_run", READY_TO_RUN: "ready_to_run", RUNNING: "running" },
        getDetails: () => null, getIsInstalled: () => false, runningState: () => "cannot_run",
      },
      runtime: {
        OnInstalledReason: { CHROME_UPDATE: "chrome_update", INSTALL: "install", SHARED_MODULE_UPDATE: "shared_module_update", UPDATE: "update" },
        OnRestartRequiredReason: { APP_UPDATE: "app_update", OS_UPDATE: "os_update", PERIODIC: "periodic" },
        PlatformArch: { ARM: "arm", ARM64: "arm64", MIPS: "mips", MIPS64: "mips64", X86_32: "x86-32", X86_64: "x86-64" },
        PlatformNaclArch: { ARM: "arm", MIPS: "mips", MIPS64: "mips64", X86_32: "x86-32", X86_64: "x86-64" },
        PlatformOs: { ANDROID: "android", CROS: "cros", LINUX: "linux", MAC: "mac", OPENBSD: "openbsd", WIN: "win" },
        RequestUpdateCheckStatus: { NO_UPDATE: "no_update", THROTTLED: "throttled", UPDATE_AVAILABLE: "update_available" },
        connect: () => { throw new TypeError("Invalid extension id: \\"\\""); },
        sendMessage: () => { throw new TypeError("Invalid extension id: \\"\\""); },
      },
      loadTimes, csi,
    };
    // Install as a getter so late overrides can't replace it with {}.
    try {
      Object.defineProperty(window, "chrome", { get: () => chromeObj, configurable: true });
    } catch(e) {
      try { window.chrome = chromeObj; } catch(e2){}
    }
    // Also patch whatever patchright already installed, if any.
    try {
      if (window.chrome && window.chrome.runtime && !window.chrome.runtime.OnInstalledReason) {
        Object.assign(window.chrome.runtime, chromeObj.runtime);
      }
      if (window.chrome && !window.chrome.loadTimes) window.chrome.loadTimes = loadTimes;
      if (window.chrome && !window.chrome.csi) window.chrome.csi = csi;
      if (window.chrome && !window.chrome.app) window.chrome.app = chromeObj.app;
    } catch(e){}
  } catch(e){}

  // ---- 7. permissions.query: plausible defaults ----
  try {
    const perms = window.navigator.permissions;
    if (perms && perms.query) {
      const origQ = perms.query.bind(perms);
      const PLAUSIBLE = {
        notifications: "prompt", geolocation: "prompt", camera: "prompt", microphone: "prompt",
        "clipboard-read": "prompt", "clipboard-write": "granted",
        midi: "granted", push: "prompt",
        "background-sync": "granted", "persistent-storage": "prompt",
      };
      perms.query = (p) => {
        if (p && PLAUSIBLE[p.name] !== undefined) {
          return Promise.resolve({ state: PLAUSIBLE[p.name], name: p.name, onchange: null });
        }
        try { return origQ(p); } catch(e) { return Promise.resolve({ state: "prompt", name: p && p.name, onchange: null }); }
      };
    }
  } catch(e){}

  // ---- 8. WebGL vendor/renderer — WebGL1 AND WebGL2 ----
  try {
    const UNMASKED_VENDOR = 37445, UNMASKED_RENDERER = 37446;
    const patch = (proto) => {
      if (!proto) return;
      const orig = proto.getParameter;
      proto.getParameter = function(param) {
        if (param === UNMASKED_VENDOR) return P.gpu.unmaskedVendor;
        if (param === UNMASKED_RENDERER) return P.gpu.unmaskedRenderer;
        if (param === 0x1F00 /* VENDOR */) return "WebKit";
        if (param === 0x1F01 /* RENDERER */) return "WebKit WebGL";
        if (param === 0x1F02 /* VERSION */) return "WebGL 1.0 (OpenGL ES 2.0 Chromium)";
        return orig.call(this, param);
      };
    };
    if (typeof WebGLRenderingContext !== "undefined") patch(WebGLRenderingContext.prototype);
    if (typeof WebGL2RenderingContext !== "undefined") patch(WebGL2RenderingContext.prototype);
  } catch(e){}

  // ---- 9. Canvas noise (deterministic per session) ----
  try {
    const noisify = (canvas, ctx) => {
      if (!ctx || !canvas || !canvas.width || !canvas.height) return;
      try {
        const w = canvas.width, h = canvas.height;
        const img = ctx.getImageData(0, 0, w, h);
        const d = img.data;
        for (let i = 0; i < d.length; i += 4) {
          d[i]     = d[i]     ^ ((rng() * 4) | 0);
          d[i + 1] = d[i + 1] ^ ((rng() * 4) | 0);
          d[i + 2] = d[i + 2] ^ ((rng() * 4) | 0);
        }
        ctx.putImageData(img, 0, 0);
      } catch(e) {}
    };
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
      try { noisify(this, this.getContext("2d")); } catch(e){}
      return origToDataURL.apply(this, args);
    };
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function(...args) {
      try { noisify(this, this.getContext("2d")); } catch(e){}
      return origToBlob.apply(this, args);
    };
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {
      const img = origGetImageData.apply(this, args);
      try {
        const d = img.data;
        for (let i = 0; i < d.length; i += 4) {
          d[i]     = d[i]     ^ ((rng() * 4) | 0);
          d[i + 1] = d[i + 1] ^ ((rng() * 4) | 0);
          d[i + 2] = d[i + 2] ^ ((rng() * 4) | 0);
        }
      } catch(e) {}
      return img;
    };
  } catch(e){}

  // ---- 10. AudioContext noise ----
  try {
    if (typeof AudioBuffer !== "undefined") {
      const origGCD = AudioBuffer.prototype.getChannelData;
      AudioBuffer.prototype.getChannelData = function(...args) {
        const r = origGCD.apply(this, args);
        try {
          for (let i = 0; i < r.length; i += 100) {
            r[i] = r[i] + (rng() - 0.5) * 1e-7;
          }
        } catch(e){}
        return r;
      };
    }
    if (typeof AnalyserNode !== "undefined") {
      const origFFD = AnalyserNode.prototype.getFloatFrequencyData;
      AnalyserNode.prototype.getFloatFrequencyData = function(array) {
        origFFD.call(this, array);
        try {
          for (let i = 0; i < array.length; i += 10) {
            array[i] = array[i] + (rng() - 0.5) * 0.1;
          }
        } catch(e){}
      };
    }
  } catch(e){}

  // ---- 11. WebRTC leak block ----
  try {
    const blocked = function() { throw new DOMException("Operation is not supported", "NotSupportedError"); };
    try { window.RTCPeerConnection = blocked; } catch(e){}
    try { window.webkitRTCPeerConnection = blocked; } catch(e){}
    try { window.RTCDataChannel = blocked; } catch(e){}
  } catch(e){}

  // ---- 12. MediaDevices: realistic default device list ----
  try {
    const fakeDevices = [
      { deviceId: "default", kind: "audioinput", label: "", groupId: "group-default-in" },
      { deviceId: "communications", kind: "audioinput", label: "", groupId: "group-default-in" },
      { deviceId: "default", kind: "audiooutput", label: "", groupId: "group-default-out" },
      { deviceId: "communications", kind: "audiooutput", label: "", groupId: "group-default-out" },
    ];
    const enumerateFn = () => Promise.resolve(fakeDevices.map((d) => ({ ...d, toJSON: () => d })));
    if (navigator.mediaDevices) {
      try { navigator.mediaDevices.enumerateDevices = enumerateFn; } catch(e){}
    } else {
      try {
        Object.defineProperty(Navigator.prototype, "mediaDevices", {
          configurable: true,
          get: () => ({
            enumerateDevices: enumerateFn,
            getUserMedia: () => Promise.reject(new DOMException("Not allowed", "NotAllowedError")),
            addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
          }),
        });
      } catch(e){}
    }
  } catch(e){}

  // ---- 13. Battery API — real laptop state ----
  try {
    const fakeBattery = {
      charging: true, chargingTime: Infinity, dischargingTime: Infinity, level: 0.87,
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
      onchargingchange: null, onchargingtimechange: null,
      ondischargingtimechange: null, onlevelchange: null,
    };
    Navigator.prototype.getBattery = () => Promise.resolve(fakeBattery);
  } catch(e){}

  // ---- 14. Screen / window dimensions ----
  try {
    const s = P.screen;
    Object.defineProperty(window.screen, "width",       { get: () => s.width });
    Object.defineProperty(window.screen, "height",      { get: () => s.height });
    Object.defineProperty(window.screen, "availWidth",  { get: () => s.availWidth });
    Object.defineProperty(window.screen, "availHeight", { get: () => s.availHeight });
    Object.defineProperty(window.screen, "availLeft",   { get: () => 0 });
    Object.defineProperty(window.screen, "availTop",    { get: () => 0 });
    Object.defineProperty(window.screen, "colorDepth",  { get: () => 24 });
    Object.defineProperty(window.screen, "pixelDepth",  { get: () => 24 });
    Object.defineProperty(window, "devicePixelRatio",   { get: () => P.dpr });
  } catch(e){}

  // ---- 15. Intl.DateTimeFormat timezone ----
  try {
    const OrigDTF = Intl.DateTimeFormat;
    const origResolved = OrigDTF.prototype.resolvedOptions;
    OrigDTF.prototype.resolvedOptions = function() {
      const r = origResolved.call(this);
      r.timeZone = P.timezone;
      r.locale = r.locale || P.locale;
      return r;
    };
    const origGTO = Date.prototype.getTimezoneOffset;
    Date.prototype.getTimezoneOffset = function() {
      try {
        const dtf = new OrigDTF("en-US", { timeZone: P.timezone, timeZoneName: "shortOffset" });
        const parts = dtf.formatToParts(this);
        const tz = parts.find((p) => p.type === "timeZoneName");
        if (tz) {
          const m = tz.value.match(/GMT([+-])(\\d{1,2})(?::?(\\d{2}))?/);
          if (m) {
            const sign = m[1] === "+" ? -1 : 1;
            const hours = parseInt(m[2], 10);
            const mins = m[3] ? parseInt(m[3], 10) : 0;
            return sign * (hours * 60 + mins);
          }
        }
      } catch(e){}
      return origGTO.call(this);
    };
  } catch(e){}

  // ---- 16. Iframe contentWindow: leave default getter to avoid breakage ----

  // ---- 17. Notification permission default ----
  try {
    if (typeof Notification !== "undefined") {
      Object.defineProperty(Notification, "permission", { get: () => "default" });
    }
  } catch(e){}

  // ---- 18. Function toString stability for patched methods ----
  try {
    const origToString = Function.prototype.toString;
    const patched = [
      window.navigator.permissions && window.navigator.permissions.query,
      HTMLCanvasElement.prototype.toDataURL,
      HTMLCanvasElement.prototype.toBlob,
      CanvasRenderingContext2D.prototype.getImageData,
      typeof WebGLRenderingContext !== "undefined" ? WebGLRenderingContext.prototype.getParameter : null,
      typeof WebGL2RenderingContext !== "undefined" ? WebGL2RenderingContext.prototype.getParameter : null,
    ].filter(Boolean);
    Function.prototype.toString = function() {
      try {
        if (patched.includes(this)) return "function " + (this.name || "") + "() { [native code] }";
      } catch(e){}
      return origToString.call(this);
    };
  } catch(e){}
})();`;
}

module.exports = { buildStealthInitScript };
