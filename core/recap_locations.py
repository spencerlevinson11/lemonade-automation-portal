"""Normalize Order Tracker recap locations to city-only group headings.

This is deliberately conservative: remove only recognizable trailing U.S.
state/postal text, not words in the actual city name.
"""
import re

US_STATE_CODES = frozenset('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split())
US_STATE_NAMES = frozenset('''alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|district of columbia'''.split('|'))
_ZIP_END = re.compile(r'(?:[\s,]+)\d{5}(?:-\d{4})?$', re.IGNORECASE)


def recap_city(raw):
    """Return the display city; ignore state and ZIP when supplied.

    Unrecognized non-US qualifiers are kept, avoiding accidental merging of
    distinct international locations.
    """
    value = re.sub(r'\s+', ' ', str(raw or '')).strip().strip(',')
    if not value:
        return 'Unspecified Location'
    value = _ZIP_END.sub('', value).strip().strip(',')
    # Handle comma-separated addresses such as 'Miami, FL' or 'Miami, Florida'.
    if ',' in value:
        city, suffix = value.rsplit(',', 1)
        if suffix.strip().casefold() in US_STATE_NAMES or suffix.strip().upper() in US_STATE_CODES:
            value = city.strip()
    # Handle 'Miami FL' and 'Miami Florida' (longest state name first).
    for state in sorted(US_STATE_NAMES, key=len, reverse=True):
        ending = ' ' + state
        if value.casefold().endswith(ending) and len(value) > len(ending):
            value = value[:-len(ending)].rstrip(' ,')
            break
    else:
        parts = value.rsplit(' ', 1)
        if len(parts) == 2 and parts[1].upper() in US_STATE_CODES and parts[0].strip():
            value = parts[0].strip(' ,')
    return value or 'Unspecified Location'
