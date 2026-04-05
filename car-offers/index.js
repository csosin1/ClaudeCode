#!/usr/bin/env node

const { getCarvanaOffer } = require('./lib/carvana');
const config = require('./lib/config');

async function main() {
  const [,, command, vin, mileage, zip] = process.argv;

  if (!command) {
    console.log('Usage:');
    console.log('  node index.js carvana <vin> <mileage> <zip>');
    console.log('');
    console.log('Example:');
    console.log('  node index.js carvana 1HGBH41JXMN109186 45000 06880');
    process.exit(1);
  }

  if (command === 'carvana') {
    if (!vin || !mileage || !zip) {
      console.error('Error: carvana command requires <vin> <mileage> <zip>');
      console.error('Example: node index.js carvana 1HGBH41JXMN109186 45000 06880');
      process.exit(1);
    }

    console.log(`Getting Carvana offer for VIN=${vin} mileage=${mileage} zip=${zip}`);
    const result = await getCarvanaOffer({
      vin,
      mileage,
      zip,
      email: config.PROJECT_EMAIL,
    });

    console.log('\n--- Result ---');
    console.log(JSON.stringify(result, null, 2));

    if (result.error) {
      process.exit(1);
    }
  } else {
    console.error(`Unknown command: ${command}`);
    console.error('Available commands: carvana');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
