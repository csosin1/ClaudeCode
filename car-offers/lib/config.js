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
  // Paid human-loop (Prolific + MTurk) — credentials are sensitive, never echo back.
  PROLIFIC_TOKEN: process.env.PROLIFIC_TOKEN || '',
  PROLIFIC_BALANCE_USD: parseInt(process.env.PROLIFIC_BALANCE_USD, 10) || 0,
  MTURK_ACCESS_KEY_ID: process.env.MTURK_ACCESS_KEY_ID || '',
  MTURK_SECRET_ACCESS_KEY: process.env.MTURK_SECRET_ACCESS_KEY || '',
  MTURK_BALANCE_USD: parseInt(process.env.MTURK_BALANCE_USD, 10) || 0,
  HUMANLOOP_DAILY_CAP_USD: parseInt(process.env.HUMANLOOP_DAILY_CAP_USD, 10) || 50,
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
  config.PROLIFIC_TOKEN = parsed.PROLIFIC_TOKEN || '';
  config.PROLIFIC_BALANCE_USD = parseInt(parsed.PROLIFIC_BALANCE_USD, 10) || 0;
  config.MTURK_ACCESS_KEY_ID = parsed.MTURK_ACCESS_KEY_ID || '';
  config.MTURK_SECRET_ACCESS_KEY = parsed.MTURK_SECRET_ACCESS_KEY || '';
  config.MTURK_BALANCE_USD = parseInt(parsed.MTURK_BALANCE_USD, 10) || 0;
  config.HUMANLOOP_DAILY_CAP_USD = parseInt(parsed.HUMANLOOP_DAILY_CAP_USD, 10) || 50;
};

module.exports = config;
// Deploy trigger: check-carvana-result
