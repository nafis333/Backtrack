def get_pip_size(symbol):
    """
    Returns the pip size for the given symbol.
      - XAUUSD: 0.1
      - XAGUSD: 0.01
      - NAS100/US30: 1.0
      - USOIL/UKOIL: 0.1
      - Forex: If symbol contains "JPY", return 0.01; otherwise, 0.0001.
    """
    sym = symbol.upper()
    if sym == "XAUUSD":
        return 0.1
    elif sym == "XAGUSD":
        return 0.01
    elif sym in {"NAS100", "US30"}:
        return 1.0
    elif sym in {"USOIL", "UKOIL"}:
        return 0.1
    else:
        return 0.01 if "JPY" in sym else 0.0001
