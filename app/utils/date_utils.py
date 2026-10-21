import jdatetime


def jalali_to_gregorian(
    date_str: str,
    time_str: str,
):
    # Reject a Gregorian year such as 2026/10/10 instead of silently treating
    # it as a far-future Jalali date. The clinic only accepts current-era
    # Jalali years; malformed values still fall through to strptime's error.
    year_text = date_str.strip().split("/")[0]
    if year_text.isdigit() and not 1200 <= int(year_text) <= 1600:
        raise ValueError("date must be a Jalali date")

    jalali_date = jdatetime.datetime.strptime(
        f"{date_str} {time_str}",
        "%Y/%m/%d %H:%M",
    )

    return jalali_date.togregorian()


def gregorian_to_jalali(dt):
    jalali_date = jdatetime.datetime.fromgregorian(
        datetime=dt
    )

    return (
        jalali_date.strftime("%Y/%m/%d"),
        jalali_date.strftime("%H:%M"),
    )