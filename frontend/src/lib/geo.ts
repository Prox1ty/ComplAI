// ISO-3166-1 alpha-2 codes; display names come from Intl.DisplayNames.
const CODES =
  'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split(
    ' ',
  )

let names: Intl.DisplayNames | null = null
try {
  names = new Intl.DisplayNames(['en'], { type: 'region' })
} catch {
  names = null
}

export const countryName = (code: string): string => names?.of(code) ?? code

export const COUNTRIES = CODES.map((code) => ({ code, name: countryName(code) })).sort((a, b) =>
  a.name.localeCompare(b.name),
)

export const REGIONS: Record<string, string[]> = {
  PK: ['Punjab', 'Sindh', 'Khyber Pakhtunkhwa', 'Balochistan', 'Islamabad Capital Territory', 'Gilgit-Baltistan', 'Azad Jammu and Kashmir'],
  US: ['NY', 'CA', 'TX', 'FL', 'IL', 'MA', 'NJ', 'WA', 'DE', 'NV'],
  IN: ['Maharashtra', 'Karnataka', 'Delhi', 'Tamil Nadu', 'Gujarat', 'Telangana', 'West Bengal'],
  AE: ['Abu Dhabi', 'Dubai', 'Sharjah', 'Dubai International Financial Centre', 'Abu Dhabi Global Market'],
  GB: ['England', 'Scotland', 'Wales', 'Northern Ireland'],
  CA: ['Ontario', 'Quebec', 'British Columbia', 'Alberta'],
  AU: ['New South Wales', 'Victoria', 'Queensland', 'Western Australia'],
  DE: ['Bavaria', 'Hesse', 'Berlin', 'North Rhine-Westphalia'],
}

export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function allTimezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  try {
    return intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : ['UTC']
  } catch {
    return ['UTC']
  }
}

export function jurisdictionLabel(i: { country: string; region?: string | null; city?: string | null }): string {
  return [countryName(i.country), i.region, i.city].filter(Boolean).join(' · ')
}
