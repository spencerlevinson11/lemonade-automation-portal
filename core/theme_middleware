from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin


NABER_USERNAME = "maudnaber"
NABER_COMPANY_NAME = "naber plastics"


def _norm(value):
    return str(value or "").strip().lower()


def _is_naber_user(request) -> bool:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if _norm(getattr(user, "username", "")) == NABER_USERNAME:
        return True

    try:
        from core.models import Company
        return Company.objects.filter(owner=user, name__iexact="Naber Plastics").exists()
    except Exception:
        return False


NABER_THEME_INJECTION = r'''
<style id="naber-plastics-global-theme">
    :root {
        --bg-main: #07130f !important;
        --bg-surface: #0b1d17 !important;
        --bg-card: #10251d !important;
        --accent: #7cc242 !important;
        --accent-strong: #a3d65c !important;
        --accent-soft: rgba(124, 194, 66, 0.18) !important;
        --text-main: #eef7ef !important;
        --text-muted: #b8c8bd !important;
        --border-subtle: rgba(124, 194, 66, 0.30) !important;
        --border-strong: rgba(124, 194, 66, 0.58) !important;
    }

    html, body {
        background:
            radial-gradient(circle at 16% 0%, rgba(124, 194, 66, 0.24), transparent 36%),
            radial-gradient(circle at 100% 100%, rgba(20, 105, 64, 0.36), transparent 45%),
            #07130f !important;
        color: var(--text-main) !important;
    }

    body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image:
            linear-gradient(rgba(124, 194, 66, 0.045) 1px, transparent 1px),
            linear-gradient(90deg, rgba(124, 194, 66, 0.045) 1px, transparent 1px);
        background-size: 36px 36px;
        opacity: 0.55;
        z-index: 0;
    }

    .page, .portal-shell, .dashboard-shell, main {
        background:
            linear-gradient(145deg, rgba(11, 29, 23, 0.98), rgba(2, 12, 8, 0.98)) !important;
        border-color: var(--border-subtle) !important;
        box-shadow: 0 24px 70px rgba(0, 0, 0, 0.48), 0 0 0 1px rgba(124, 194, 66, 0.10) !important;
    }

    .card, .panel, .section, .content-card, .auth-wrapper .card, .tracker-card,
    .metric-card, .project-card, .schedule-card, .quote-card, .form-card,
    .table-card, .map-card, .automation-card, .status-company {
        background:
            radial-gradient(circle at top left, rgba(124, 194, 66, 0.15), transparent 50%),
            #10251d !important;
        border-color: var(--border-subtle) !important;
    }

    .brand-logo, .logo-mark, .glow-dot {
        background: radial-gradient(circle at 30% 20%, #e0ffc0, #7cc242 52%, #315f22) !important;
        box-shadow: 0 0 18px rgba(124, 194, 66, 0.95), 0 0 42px rgba(124, 194, 66, 0.45) !important;
    }

    .brand-logo::after, .logo-mark::after {
        content: "NP" !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: absolute !important;
        inset: 0 !important;
        border: 0 !important;
        color: #082015 !important;
        font-size: 0.62rem !important;
        font-weight: 900 !important;
        letter-spacing: -0.04em !important;
    }

    a, .user-pill a, .nav-link, .link, strong, .accent, .brand-text-main {
        color: var(--accent-strong) !important;
    }

    button, .btn, .run-btn, .primary-btn, input[type="submit"], .action-btn {
        background: linear-gradient(135deg, rgba(124, 194, 66, 0.25), rgba(20, 105, 64, 0.24)) !important;
        border-color: rgba(124, 194, 66, 0.58) !important;
        color: #f4fff1 !important;
    }

    button:hover, .btn:hover, .run-btn:hover, .primary-btn:hover, input[type="submit"]:hover, .action-btn:hover {
        box-shadow: 0 0 0 1px rgba(124, 194, 66, 0.45), 0 12px 32px rgba(124, 194, 66, 0.20) !important;
    }

    input:focus, select:focus, textarea:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 1px rgba(124, 194, 66, 0.42), 0 0 0 4px rgba(124, 194, 66, 0.14) !important;
        outline: none !important;
    }

    table tr:hover, .automation-row:hover, .order-row:hover, .list-row:hover {
        background: rgba(124, 194, 66, 0.09) !important;
    }
</style>
<script id="naber-plastics-branding-script">
(function () {
    function replaceExact(selector, oldText, newText) {
        document.querySelectorAll(selector).forEach(function (el) {
            if ((el.textContent || '').trim() === oldText) el.textContent = newText;
        });
    }
    function replaceIncludes(selector, oldText, newText) {
        document.querySelectorAll(selector).forEach(function (el) {
            if ((el.textContent || '').indexOf(oldText) !== -1) el.textContent = newText;
        });
    }
    document.addEventListener('DOMContentLoaded', function () {
        replaceExact('.brand-text-main', 'AUTOMATION PORTAL', 'NABER PLASTICS PORTAL');
        replaceExact('.brand-text-sub', 'Control center for your client workflows', 'Sustainable plastics workflow center');
        replaceIncludes('h1', 'Welcome to your automation dashboard', 'Welcome to your Naber Plastics dashboard');
        document.title = document.title.replace('Your Automation Portal', 'Naber Plastics Portal');
    });
})();
</script>
'''


class NaberThemeMiddleware(MiddlewareMixin):
    """Inject the Naber theme into HTML responses for MaudNaber only.

    This avoids touching every template. It runs after authentication middleware,
    detects the logged-in user, and inserts the theme just before </head>.
    """

    def process_response(self, request, response):
        if not _is_naber_user(request):
            return response

        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return response

        if getattr(response, "streaming", False):
            return response

        try:
            html = response.content.decode(response.charset or "utf-8")
        except Exception:
            return response

        if 'id="naber-plastics-global-theme"' in html:
            return response

        lower_html = html.lower()
        head_index = lower_html.rfind("</head>")
        if head_index == -1:
            return response

        html = html[:head_index] + NABER_THEME_INJECTION + html[head_index:]
        response.content = html.encode(response.charset or "utf-8")
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
