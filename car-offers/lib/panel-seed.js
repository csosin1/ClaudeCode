/**
 * Panel seed — 12 real consumers for the longitudinal panel.
 *
 * Each entry is one PERMANENT identity:
 *   - One real VIN (sourced from public dealer listings + validated via
 *     NHTSA vPIC decoder).
 *   - One home ZIP (real populous metro in the US; zips span Northeast,
 *     South, Midwest, West, Mountain regions as required by the spec).
 *   - One fingerprint_profile_id (index into lib/fingerprint.PROFILES).
 *   - One biweekly_slot (day-of-fortnight 0..13) + shop_hour_local (UTC
 *     hour 9..21) so the cron can find them deterministically.
 *
 * The proxy_session_id is a stable prefix — the actual Decodo sticky
 * session within its 23h TTL is this prefix + a random suffix. Consumer
 * identity persists across session rolls because the prefix matches.
 *
 * Mix breakdown:
 *   Economy (4): Civic x2, Corolla, Elantra
 *   Mid-size (4): Accord, RAV4, CR-V (via Mazda CX-5), F-150*
 *     * F-150 is the "mid-size" truck slot; spec also asks for 2 trucks
 *       so it double-counts and we add Silverado on the premium/truck side
 *   Premium/luxury (4): Lexus RX, BMW X3, Tesla Model 3, Silverado*
 *     * Silverado Custom is large-truck premium-adjacent
 *
 * Body style: 6 sedans + 4 SUVs + 2 trucks = 12. Meets spec floor of
 * 4 sedans + 4 SUVs + 2 trucks + 2 anything (anything = 2 extra sedans).
 *
 * Year spread: 2019, 2020, 2021 x3, 2022 x5, 2023 x2 = covers every
 * required year.
 *
 * Region spread (home_zip):
 *   Northeast x4: 06880 CT, 07302 NJ, 10023 NY, 02139 MA
 *   South x3:    33139 FL, 78701 TX, 30309 GA
 *   Midwest x2:  60614 IL, 44114 OH
 *   West x2:     94110 CA, 98121 WA
 *   Mountain x1: 80202 CO
 *
 * biweekly_slot and shop_hour_local were picked to spread the panel
 * across the 14-day window (7 distinct slots, hours 13-21 UTC = 8am-4pm
 * Eastern). Two consumers may share a slot+hour — that's fine, they
 * run sequentially inside one cron fire.
 */

const CONSUMERS = [
  {
    id: 1,
    name: 'Westport CT 2022 Honda Accord',
    vin: '1HGCV2F9XNA008352',
    year: 2022, make: 'Honda', model: 'Accord', trim: 'Touring',
    mileage: 42000, home_zip: '06880', condition: 'Good',
    proxy_session_id: 'cons01-stick',
    fingerprint_profile_id: 0,  // Win10 HP laptop 1366x768
    biweekly_slot: 0, shop_hour_local: 13,
  },
  {
    id: 2,
    name: 'Jersey City NJ 2022 Honda Civic',
    vin: '2HGFE2F5XNH606212',
    year: 2022, make: 'Honda', model: 'Civic', trim: 'Sport',
    mileage: 36000, home_zip: '07302', condition: 'Good',
    proxy_session_id: 'cons02-stick',
    fingerprint_profile_id: 1,  // Win10 Dell Latitude 1440x900
    biweekly_slot: 1, shop_hour_local: 14,
  },
  {
    id: 3,
    name: 'Upper West Side NY 2020 Toyota Corolla',
    vin: 'JTDFPRAE3LJ021945',
    year: 2020, make: 'Toyota', model: 'Corolla', trim: 'XLE',
    mileage: 58000, home_zip: '10023', condition: 'Good',
    proxy_session_id: 'cons03-stick',
    fingerprint_profile_id: 2,  // Win11 Lenovo Iris Xe 1536x864
    biweekly_slot: 2, shop_hour_local: 15,
  },
  {
    id: 4,
    name: 'Cambridge MA 2023 Hyundai Elantra',
    vin: 'KMHLN4AJ5PU069598',
    year: 2023, make: 'Hyundai', model: 'Elantra', trim: 'Limited',
    mileage: 18000, home_zip: '02139', condition: 'Good',
    proxy_session_id: 'cons04-stick',
    fingerprint_profile_id: 3,  // Win10 ASUS gaming laptop GTX 1650
    biweekly_slot: 3, shop_hour_local: 13,
  },
  {
    id: 5,
    name: 'Miami Beach FL 2022 Honda Civic',
    vin: '19XFL2H88NE021488',
    year: 2022, make: 'Honda', model: 'Civic', trim: 'EX',
    mileage: 34000, home_zip: '33139', condition: 'Good',
    proxy_session_id: 'cons05-stick',
    fingerprint_profile_id: 4,  // Win11 desktop RTX 3060
    biweekly_slot: 4, shop_hour_local: 16,
  },
  {
    id: 6,
    name: 'Austin TX 2021 Toyota RAV4',
    vin: '4T3B6RFV8MU042044',
    year: 2021, make: 'Toyota', model: 'RAV4', trim: 'XLE',
    mileage: 44000, home_zip: '78701', condition: 'Good',
    proxy_session_id: 'cons06-stick',
    fingerprint_profile_id: 5,  // Win10 desktop AMD RX 6600 2560x1440
    biweekly_slot: 5, shop_hour_local: 17,
  },
  {
    id: 7,
    name: 'Atlanta GA 2022 Ford F-150',
    vin: '1FTEW1C51NFA83735',
    year: 2022, make: 'Ford', model: 'F-150', trim: 'SuperCrew',
    mileage: 38000, home_zip: '30309', condition: 'Good',
    proxy_session_id: 'cons07-stick',
    fingerprint_profile_id: 6,  // Win11 office desktop Intel UHD 770
    biweekly_slot: 6, shop_hour_local: 18,
  },
  {
    id: 8,
    name: 'Chicago IL 2019 Mazda CX-5',
    vin: 'JM3KFBCM7K1635710',
    year: 2019, make: 'Mazda', model: 'CX-5', trim: 'Touring',
    mileage: 68000, home_zip: '60614', condition: 'Good',
    proxy_session_id: 'cons08-stick',
    fingerprint_profile_id: 7,  // Win10 desktop RTX 2060
    biweekly_slot: 7, shop_hour_local: 14,
  },
  {
    id: 9,
    name: 'Cleveland OH 2021 Chevrolet Silverado',
    vin: '3GCPYBEK5MG259842',
    year: 2021, make: 'Chevrolet', model: 'Silverado 1500', trim: 'Custom',
    mileage: 52000, home_zip: '44114', condition: 'Good',
    proxy_session_id: 'cons09-stick',
    fingerprint_profile_id: 8,  // MacBook Air M1 13"
    biweekly_slot: 8, shop_hour_local: 15,
  },
  {
    id: 10,
    name: 'San Francisco CA 2022 Tesla Model 3',
    vin: '5YJ3E1EB1NF139108',
    year: 2022, make: 'Tesla', model: 'Model 3', trim: 'Long Range',
    mileage: 32000, home_zip: '94110', condition: 'Good',
    proxy_session_id: 'cons10-stick',
    fingerprint_profile_id: 9,  // MacBook Air M2 13"
    biweekly_slot: 9, shop_hour_local: 16,
  },
  {
    id: 11,
    name: 'Seattle WA 2021 BMW X3',
    vin: '5UXTY5C06M9G23799',
    year: 2021, make: 'BMW', model: 'X3', trim: 'xDrive30i',
    mileage: 42000, home_zip: '98121', condition: 'Good',
    proxy_session_id: 'cons11-stick',
    fingerprint_profile_id: 10, // iMac 27" M1
    biweekly_slot: 10, shop_hour_local: 17,
  },
  {
    id: 12,
    name: 'Denver CO 2023 Lexus RX 350',
    vin: '2T2BAMCA9PC007784',
    year: 2023, make: 'Lexus', model: 'RX 350', trim: 'Premium',
    mileage: 22000, home_zip: '80202', condition: 'Good',
    proxy_session_id: 'cons12-stick',
    fingerprint_profile_id: 11, // Mac Mini M2
    biweekly_slot: 11, shop_hour_local: 18,
  },
];

module.exports = { CONSUMERS };
