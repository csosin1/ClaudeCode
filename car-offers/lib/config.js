const path = require('path');
const fs = require('fs');
const dotenv = require('dotenv');

const envPath = path.join(__dirname, '..', '.env');
dotenv.config({ path: envPath });

const config = {
  PROXY_HOST: process.env.PROXY_HOST || '',
  PROXY_PORT: process.env.PROXY_PORT || '',
  PROXY_USER: process.env.PROXY_USER || '',
  PROXY_PASS: process.env.PROXY_PASS || '',
  PROJECT_EMAIL: process.env.PROJECT_EMAIL || '',
  PORT: parseInt(process.env.PORT, 10) || 3100,
};

/**
 * Returns true if proxy is fully configured (host/port/user are pre-filled,
 * so only PROXY_PASS needs to be added by the user via /setup).
 */
config.isConfigured = function () {
  return !!(config.PROXY_HOST && config.PROXY_PASS);
};

/**
 * Re-reads the .env file from disk and updates the config object in place.
 * Call this after writing a new .env so the running process picks up changes.
 */
config.reloadConfig = function () {
  const parsed = dotenv.parse(fs.readFileSync(envPath, 'utf8'));
  config.PROXY_HOST = parsed.PROXY_HOST || '';
  config.PROXY_PORT = parsed.PROXY_PORT || '';
  config.PROXY_USER = parsed.PROXY_USER || '';
  config.PROXY_PASS = parsed.PROXY_PASS || '';
  config.PROJECT_EMAIL = parsed.PROJECT_EMAIL || '';
  config.PORT = parseInt(parsed.PORT, 10) || 3100;
};

module.exports = config;
// Deploy trigger: nginx-recovery-v2
