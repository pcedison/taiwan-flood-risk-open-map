from __future__ import annotations

import ssl

from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context


def test_taiwan_gov_open_data_ssl_context_keeps_verification_without_strict_ski() -> None:
    context = taiwan_gov_open_data_ssl_context()
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)

    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    if strict:
        assert not context.verify_flags & strict
