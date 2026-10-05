import jdatetime


def jalali_to_gregorian(
    date_str: str,
    time_str: str,
):
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