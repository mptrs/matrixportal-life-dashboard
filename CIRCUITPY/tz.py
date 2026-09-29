# tz.py - tijdzones met zomertijd, zonder internet.
# Een zone is (standaard UTC-offset in uren, zomertijdregel):
#   "EU" - laatste zondag maart t/m laatste zondag oktober, 01:00 UTC (Amsterdam, Londen, ...)
#   "US" - tweede zondag maart t/m eerste zondag november, 02:00 lokaal
#   "AU" - eerste zondag oktober t/m eerste zondag april (Sydney, Melbourne)
#   None - geen zomertijd (Tokio, Singapore, Dubai, ...)

_DIM = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def weekday(y, m, d):
    """0 = maandag."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d + 6) % 7


def _days(y, m, d):
    """Dagen sinds 1-1-1970."""
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def _wall(y, m, d, hour):
    return _days(y, m, d) * 86400 + hour * 3600


def _sunday(y, m, n):
    """De n-de zondag van de maand, of de laatste bij n = -1."""
    first = 1 + (6 - weekday(y, m, 1)) % 7
    if n > 0:
        return first + 7 * (n - 1)
    return first + 7 * ((_DIM[m - 1] - first) // 7)


def utc_offset(unix, std_hours, rule=None):
    """Offset in seconden t.o.v. UTC op tijdstip unix (UTC)."""
    std = int(std_hours * 3600)
    if rule is None:
        return std
    # Rond jaarwisseling kan dit jaartal een dag afwijken; dan is het zomertijd-antwoord
    # in beide jaren hetzelfde, dus dat maakt niet uit.
    y = 1970 + (unix // 86400) * 400 // 146097
    if rule == "EU":
        dst = _wall(y, 3, _sunday(y, 3, -1), 1) <= unix < _wall(y, 10, _sunday(y, 10, -1), 1)
    elif rule == "US":
        start = _wall(y, 3, _sunday(y, 3, 2), 2) - std
        end = _wall(y, 11, _sunday(y, 11, 1), 2) - std - 3600
        dst = start <= unix < end
    elif rule == "AU":
        end = _wall(y, 4, _sunday(y, 4, 1), 3) - std - 3600
        start = _wall(y, 10, _sunday(y, 10, 1), 2) - std
        dst = not end <= unix < start
    else:
        dst = False
    return std + 3600 if dst else std
