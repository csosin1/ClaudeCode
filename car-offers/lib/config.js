const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

module.exports = {
  PROXY_HOST: process.env.PROXY_HOST || '',
  PROXY_PORT: process.env.PROXY_PORT || '',
  PROXY_USER: process.env.PROXY_USER || '',
  PROXY_PASS: process.env.PROXY_PASS || '',
  PROJECT_EMAIL: process.env.PROJECT_EMAIL || '',
  PORT: parseInt(process.env.PORT, 10) || 3100,
};
