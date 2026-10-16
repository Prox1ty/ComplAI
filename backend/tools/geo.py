"""ISO-3166 alpha-2 code to English country name (common banking jurisdictions;
unknown codes fall back to the code itself)."""
from __future__ import annotations

NAMES = {
    "AE": "United Arab Emirates", "AF": "Afghanistan", "AR": "Argentina", "AT": "Austria", "AU": "Australia",
    "BD": "Bangladesh", "BE": "Belgium", "BG": "Bulgaria", "BH": "Bahrain", "BR": "Brazil", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia", "CY": "Cyprus", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "ET": "Ethiopia",
    "FI": "Finland", "FR": "France", "GB": "United Kingdom", "GH": "Ghana", "GR": "Greece", "HK": "Hong Kong",
    "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IQ": "Iraq", "IT": "Italy", "JO": "Jordan", "JP": "Japan", "KE": "Kenya", "KR": "South Korea", "KW": "Kuwait",
    "KZ": "Kazakhstan", "LB": "Lebanon", "LK": "Sri Lanka", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "MA": "Morocco", "MT": "Malta", "MU": "Mauritius", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria",
    "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NZ": "New Zealand", "OM": "Oman", "PE": "Peru",
    "PH": "Philippines", "PK": "Pakistan", "PL": "Poland", "PT": "Portugal", "QA": "Qatar", "RO": "Romania",
    "RS": "Serbia", "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore",
    "SI": "Slovenia", "SK": "Slovakia", "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey", "TW": "Taiwan",
    "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda", "US": "United States", "UZ": "Uzbekistan",
    "VN": "Vietnam", "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe",
}


def country_name(code: str) -> str:
    return NAMES.get((code or "").upper(), code)
