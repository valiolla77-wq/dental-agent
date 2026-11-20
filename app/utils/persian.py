"""Small Persian text helpers shared by user-facing messages."""

_TO_PERSIAN = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(value: object) -> str:
    """Render Latin/Arabic-Indic digits as Persian digits (``09:00`` → ``۰۹:۰۰``).

    Only for text shown to people. Machine-readable values (tool arguments,
    stored dates) keep Latin digits.
    """
    return str(value).translate(_TO_PERSIAN)
