from __future__ import annotations

import ssl


def taiwan_gov_open_data_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        # Keep CA and hostname verification; only tolerate government chains missing SKI.
        context.verify_flags &= ~strict
    return context
