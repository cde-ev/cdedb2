#!/usr/bin/env python3
from typing import Any, Dict, Optional

from cdedb.script import make_backend, setup, Script, CoreBackend
from cdedb.validationdata import COUNTRY_CODES

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")()

DRY_RUN = True

# Prepare stuff

code_to_english = {
    "AF": "Afghanistan",
    "AX": "Åland Islands",
    "AL": "Albania",
    "DZ": "Algeria",
    "AS": "American Samoa",
    "AD": "Andorra",
    "AO": "Angola",
    "AI": "Anguilla",
    "AQ": "Antarctica",
    "AG": "Antigua & Barbuda",
    "AR": "Argentina",
    "AM": "Armenia",
    "AW": "Aruba",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgium",
    "BZ": "Belize",
    "BJ": "Benin",
    "BM": "Bermuda",
    "BT": "Bhutan",
    "BO": "Bolivia",
    "BA": "Bosnia & Herzegovina",
    "BW": "Botswana",
    "BV": "Bouvet Island",
    "BR": "Brazil",
    "IO": "British Indian Ocean Territory",
    "VG": "British Virgin Islands",
    "BN": "Brunei",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "KH": "Cambodia",
    "CM": "Cameroon",
    "CA": "Canada",
    "CV": "Cape Verde",
    "BQ": "Caribbean Netherlands",
    "KY": "Cayman Islands",
    "CF": "Central African Republic",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CX": "Christmas Island",
    "CC": "Cocos (Keeling) Islands",
    "CO": "Colombia",
    "KM": "Comoros",
    "CG": "Congo - Brazzaville",
    "CD": "Congo - Kinshasa",
    "CK": "Cook Islands",
    "CR": "Costa Rica",
    "CI": "Côte d’Ivoire",
    "HR": "Croatia",
    "CU": "Cuba",
    "CW": "Curaçao",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DK": "Denmark",
    "DJ": "Djibouti",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EG": "Egypt",
    "SV": "El Salvador",
    "GQ": "Equatorial Guinea",
    "ER": "Eritrea",
    "EE": "Estonia",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "FK": "Falkland Islands",
    "FO": "Faroe Islands",
    "FJ": "Fiji",
    "FI": "Finland",
    "FR": "France",
    "GF": "French Guiana",
    "PF": "French Polynesia",
    "TF": "French Southern Territories",
    "GA": "Gabon",
    "GM": "Gambia",
    "GE": "Georgia",
    "DE": "Germany",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GR": "Greece",
    "GL": "Greenland",
    "GD": "Grenada",
    "GP": "Guadeloupe",
    "GU": "Guam",
    "GT": "Guatemala",
    "GG": "Guernsey",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HM": "Heard & McDonald Islands",
    "HN": "Honduras",
    "HK": "Hong Kong SAR China",
    "HU": "Hungary",
    "IS": "Iceland",
    "IN": "India",
    "ID": "Indonesia",
    "IR": "Iran",
    "IQ": "Iraq",
    "IE": "Ireland",
    "IM": "Isle of Man",
    "IL": "Israel",
    "IT": "Italy",
    "JM": "Jamaica",
    "JP": "Japan",
    "JE": "Jersey",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KE": "Kenya",
    "KI": "Kiribati",
    "KW": "Kuwait",
    "KG": "Kyrgyzstan",
    "LA": "Laos",
    "LV": "Latvia",
    "LB": "Lebanon",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MO": "Macao SAR China",
    "MG": "Madagascar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Maldives",
    "ML": "Mali",
    "MT": "Malta",
    "MH": "Marshall Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "YT": "Mayotte",
    "MX": "Mexico",
    "FM": "Micronesia",
    "MD": "Moldova",
    "MC": "Monaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MS": "Montserrat",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "MM": "Myanmar (Burma)",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NL": "Netherlands",
    "NC": "New Caledonia",
    "NZ": "New Zealand",
    "NI": "Nicaragua",
    "NE": "Niger",
    "NG": "Nigeria",
    "NU": "Niue",
    "NF": "Norfolk Island",
    "KP": "North Korea",
    "MK": "North Macedonia",
    "MP": "Northern Mariana Islands",
    "NO": "Norway",
    "OM": "Oman",
    "PK": "Pakistan",
    "PW": "Palau",
    "PS": "Palestinian Territories",
    "PA": "Panama",
    "PG": "Papua New Guinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippines",
    "PN": "Pitcairn Islands",
    "PL": "Poland",
    "PT": "Portugal",
    "PR": "Puerto Rico",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RU": "Russia",
    "RW": "Rwanda",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "São Tomé & Príncipe",
    "SA": "Saudi Arabia",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "SG": "Singapore",
    "SX": "Sint Maarten",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "SB": "Solomon Islands",
    "SO": "Somalia",
    "ZA": "South Africa",
    "GS": "South Georgia & South Sandwich Islands",
    "KR": "South Korea",
    "SS": "South Sudan",
    "ES": "Spain",
    "LK": "Sri Lanka",
    "BL": "St. Barthélemy",
    "SH": "St. Helena",
    "KN": "St. Kitts & Nevis",
    "LC": "St. Lucia",
    "MF": "St. Martin",
    "PM": "St. Pierre & Miquelon",
    "VC": "St. Vincent & Grenadines",
    "SD": "Sudan",
    "SR": "Suriname",
    "SJ": "Svalbard & Jan Mayen",
    "SE": "Sweden",
    "CH": "Switzerland",
    "SY": "Syria",
    "TW": "Taiwan",
    "TJ": "Tajikistan",
    "TZ": "Tanzania",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TK": "Tokelau",
    "TO": "Tonga",
    "TT": "Trinidad & Tobago",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TM": "Turkmenistan",
    "TC": "Turks & Caicos Islands",
    "TV": "Tuvalu",
    "UM": "U.S. Outlying Islands",
    "VI": "U.S. Virgin Islands",
    "UG": "Uganda",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VU": "Vanuatu",
    "VA": "Vatican City",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "WF": "Wallis & Futuna",
    "EH": "Western Sahara",
    "YE": "Yemen",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}
code_to_german = {
    "AF": "Afghanistan",
    "EG": "Ägypten",
    "AX": "Ålandinseln",
    "AL": "Albanien",
    "DZ": "Algerien",
    "AS": "Amerikanisch-Samoa",
    "VI": "Amerikanische Jungferninseln",
    "UM": "Amerikanische Überseeinseln",
    "AD": "Andorra",
    "AO": "Angola",
    "AI": "Anguilla",
    "AQ": "Antarktis",
    "AG": "Antigua und Barbuda",
    "GQ": "Äquatorialguinea",
    "AR": "Argentinien",
    "AM": "Armenien",
    "AW": "Aruba",
    "AZ": "Aserbaidschan",
    "ET": "Äthiopien",
    "AU": "Australien",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesch",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgien",
    "BZ": "Belize",
    "BJ": "Benin",
    "BM": "Bermuda",
    "BT": "Bhutan",
    "BO": "Bolivien",
    "BQ": "Bonaire, Sint Eustatius und Saba",
    "BA": "Bosnien und Herzegowina",
    "BW": "Botsuana",
    "BV": "Bouvetinsel",
    "BR": "Brasilien",
    "VG": "Britische Jungferninseln",
    "IO": "Britisches Territorium im Indischen Ozean",
    "BN": "Brunei Darussalam",
    "BG": "Bulgarien",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "CV": "Cabo Verde",
    "CL": "Chile",
    "CN": "China",
    "CK": "Cookinseln",
    "CR": "Costa Rica",
    "CI": "Côte d’Ivoire",
    "CW": "Curaçao",
    "DK": "Dänemark",
    "DE": "Deutschland",
    "DM": "Dominica",
    "DO": "Dominikanische Republik",
    "DJ": "Dschibuti",
    "EC": "Ecuador",
    "SV": "El Salvador",
    "ER": "Eritrea",
    "EE": "Estland",
    "SZ": "Eswatini",
    "FK": "Falklandinseln",
    "FO": "Färöer",
    "FJ": "Fidschi",
    "FI": "Finnland",
    "FR": "Frankreich",
    "GF": "Französisch-Guayana",
    "PF": "Französisch-Polynesien",
    "TF": "Französische Süd- und Antarktisgebiete",
    "GA": "Gabun",
    "GM": "Gambia",
    "GE": "Georgien",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GD": "Grenada",
    "GR": "Griechenland",
    "GL": "Grönland",
    "GP": "Guadeloupe",
    "GU": "Guam",
    "GT": "Guatemala",
    "GG": "Guernsey",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HM": "Heard und McDonaldinseln",
    "HN": "Honduras",
    "IN": "Indien",
    "ID": "Indonesien",
    "IQ": "Irak",
    "IR": "Iran",
    "IE": "Irland",
    "IS": "Island",
    "IM": "Isle of Man",
    "IL": "Israel",
    "IT": "Italien",
    "JM": "Jamaika",
    "JP": "Japan",
    "YE": "Jemen",
    "JE": "Jersey",
    "JO": "Jordanien",
    "KY": "Kaimaninseln",
    "KH": "Kambodscha",
    "CM": "Kamerun",
    "CA": "Kanada",
    "KZ": "Kasachstan",
    "QA": "Katar",
    "KE": "Kenia",
    "KG": "Kirgisistan",
    "KI": "Kiribati",
    "CC": "Kokosinseln",
    "CO": "Kolumbien",
    "KM": "Komoren",
    "CG": "Kongo-Brazzaville",
    "CD": "Kongo-Kinshasa",
    "HR": "Kroatien",
    "CU": "Kuba",
    "KW": "Kuwait",
    "LA": "Laos",
    "LS": "Lesotho",
    "LV": "Lettland",
    "LB": "Libanon",
    "LR": "Liberia",
    "LY": "Libyen",
    "LI": "Liechtenstein",
    "LT": "Litauen",
    "LU": "Luxemburg",
    "MG": "Madagaskar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Malediven",
    "ML": "Mali",
    "MT": "Malta",
    "MA": "Marokko",
    "MH": "Marshallinseln",
    "MQ": "Martinique",
    "MR": "Mauretanien",
    "MU": "Mauritius",
    "YT": "Mayotte",
    "MX": "Mexiko",
    "FM": "Mikronesien",
    "MC": "Monaco",
    "MN": "Mongolei",
    "ME": "Montenegro",
    "MS": "Montserrat",
    "MZ": "Mosambik",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NC": "Neukaledonien",
    "NZ": "Neuseeland",
    "NI": "Nicaragua",
    "NL": "Niederlande",
    "NE": "Niger",
    "NG": "Nigeria",
    "NU": "Niue",
    "KP": "Nordkorea",
    "MP": "Nördliche Marianen",
    "MK": "Nordmazedonien",
    "NF": "Norfolkinsel",
    "NO": "Norwegen",
    "OM": "Oman",
    "AT": "Österreich",
    "PK": "Pakistan",
    "PS": "Palästinensische Autonomiegebiete",
    "PW": "Palau",
    "PA": "Panama",
    "PG": "Papua-Neuguinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippinen",
    "PN": "Pitcairninseln",
    "PL": "Polen",
    "PT": "Portugal",
    "PR": "Puerto Rico",
    "MD": "Republik Moldau",
    "RE": "Réunion",
    "RW": "Ruanda",
    "RO": "Rumänien",
    "RU": "Russland",
    "SB": "Salomonen",
    "ZM": "Sambia",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "São Tomé und Príncipe",
    "SA": "Saudi-Arabien",
    "SE": "Schweden",
    "CH": "Schweiz",
    "SN": "Senegal",
    "RS": "Serbien",
    "SC": "Seychellen",
    "SL": "Sierra Leone",
    "ZW": "Simbabwe",
    "SG": "Singapur",
    "SX": "Sint Maarten",
    "SK": "Slowakei",
    "SI": "Slowenien",
    "SO": "Somalia",
    "HK": "Sonderverwaltungsregion Hongkong",
    "MO": "Sonderverwaltungsregion Macau",
    "ES": "Spanien",
    "SJ": "Spitzbergen und Jan Mayen",
    "LK": "Sri Lanka",
    "BL": "St. Barthélemy",
    "SH": "St. Helena",
    "KN": "St. Kitts und Nevis",
    "LC": "St. Lucia",
    "MF": "St. Martin",
    "PM": "St. Pierre und Miquelon",
    "VC": "St. Vincent und die Grenadinen",
    "ZA": "Südafrika",
    "SD": "Sudan",
    "GS": "Südgeorgien und die Südlichen Sandwichinseln",
    "KR": "Südkorea",
    "SS": "Südsudan",
    "SR": "Suriname",
    "SY": "Syrien",
    "TJ": "Tadschikistan",
    "TW": "Taiwan",
    "TZ": "Tansania",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TK": "Tokelau",
    "TO": "Tonga",
    "TT": "Trinidad und Tobago",
    "TD": "Tschad",
    "CZ": "Tschechien",
    "TN": "Tunesien",
    "TR": "Türkei",
    "TM": "Turkmenistan",
    "TC": "Turks- und Caicosinseln",
    "TV": "Tuvalu",
    "UG": "Uganda",
    "UA": "Ukraine",
    "HU": "Ungarn",
    "UY": "Uruguay",
    "UZ": "Usbekistan",
    "VU": "Vanuatu",
    "VA": "Vatikanstadt",
    "VE": "Venezuela",
    "AE": "Vereinigte Arabische Emirate",
    "US": "Vereinigte Staaten",
    "GB": "Vereinigtes Königreich",
    "VN": "Vietnam",
    "WF": "Wallis und Futuna",
    "CX": "Weihnachtsinsel",
    "EH": "Westsahara",
    "CF": "Zentralafrikanische Republik",
    "CY": "Zypern",
}
specials_to_code = {
    # Funny Germanys
    "Alemania": "DE",
    "Baden Württemberg, Deutschland": "DE",
    "Bayern": "DE",
    "Berlin": "DE",
    "D": "DE",
    "Deutschlad": "DE",
    "Deutschland (DEU)": "DE",
    "Deutschland, Nordrhein-Westfalen": "DE",
    "Dutschland": "DE",
    "GER": "DE",
    "Hessen": "DE",
    "Niedersachsen": "DE",
    "Nordrhein-Westfalen": "DE",
    "Nordrhein-Westfalen / Deutschland": "DE",
    "NRW": "DE",

    # Other countries
    "Tschechische Republik": "CZ",
    "España": "ES",
    "Korea, Republik": "KR",
    "Moldawien": "MD",
    "Polska": "PL",
    "România": "RO",
    "Slovensko": "SK",
    "Great Britain": "GB",
    "Großbritannien": "GB",
    "Schottland": "GB",
    "Scotland": "GB",
    "UK": "GB",
    "USA": "US",
}

all_to_code = {
    **{v: k for k, v in code_to_english.items()},
    **{v: k for k, v in code_to_german.items()},
    **specials_to_code
}

core: CoreBackend = make_backend("core")

error: Dict[int, str] = {}

# Execution

with Script(rs, dry_run=DRY_RUN):
    persona_id: Optional[int] = -1
    while True:
        persona_id = core.next_persona(
            rs, persona_id=persona_id, is_member=None, is_archived=False)

        if not persona_id:
            break

        persona = core.get_total_persona(rs, persona_id)
        if not persona['is_event_realm']:
            continue

        update: Dict[str, Any] = {
            'id': persona_id,
        }

        if persona['country'] in COUNTRY_CODES:
            pass
        elif not persona['country']:
            update['country'] = "DE"
        else:
            persona['country'] = persona['country'].strip()
            if persona['country'] in all_to_code:
                update['country'] = all_to_code[persona['country']]
            else:
                error[persona_id] = persona['country']
                print(f"Failed for {persona_id}"
                      f" with country {persona['country']}.")

        if persona['is_cde_realm']:
            if persona['country2'] in COUNTRY_CODES:
                pass
            elif not persona['country2']:
                update['country2'] = "DE"
            else:
                persona['country2'] = persona['country2'].strip()
                if persona['country2'] in all_to_code:
                    update['country2'] = all_to_code[persona['country2']]
                else:
                    error[persona_id] = persona['country2']
                    print(f"Failed for {persona_id}"
                          f" with country2 {persona['country2']}.")

        if len(update) <= 1:
            continue

        core.change_persona(rs, update, may_wait=False,
                            change_note="Land auf Ländercode umgestellt.")

    if error:
        print(f"{len(error)} country rewrites failed. Aborting")
        raise RuntimeError("Not all country rewrites successful. Aborting.")
