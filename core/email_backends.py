import ssl

from django.core.mail.backends.smtp import EmailBackend


class InsecureSMTPBackend(EmailBackend):
    """
    DEV-ONLY backend that completely disables SSL certificate verification.

    This uses ssl._create_unverified_context(), which tells Python's SSL layer
    not to verify certificates at all.

    DO NOT USE THIS IN PRODUCTION.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # This creates an SSL context that skips all certificate verification.
        # It is explicitly insecure, but useful for local testing when your
        # environment hates the SMTP server's certificate chain.
        self.ssl_context = ssl._create_unverified_context()
