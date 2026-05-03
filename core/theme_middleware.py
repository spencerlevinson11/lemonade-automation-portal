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
        --bg-main: #f3f7fa !important;
        --bg-surface: #ffffff !important;
        --bg-card: #ffffff !important;
        --accent: #6cc8d6 !important;
        --accent-strong: #1f8ea8 !important;
        --accent-deep: #246b82 !important;
        --accent-soft: rgba(108, 200, 214, 0.18) !important;
        --text-main: #21343d !important;
        --text-muted: #667b86 !important;
        --border-subtle: rgba(108, 200, 214, 0.28) !important;
        --border-strong: rgba(31, 142, 168, 0.44) !important;
    }

    html, body {
        background:
            radial-gradient(circle at 0% 0%, rgba(108, 200, 214, 0.18), transparent 24%),
            radial-gradient(circle at 100% 100%, rgba(154, 219, 228, 0.20), transparent 28%),
            linear-gradient(180deg, #f8fbfd 0%, #eef5f8 100%) !important;
        color: var(--text-main) !important;
    }

    body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image:
            linear-gradient(rgba(108, 200, 214, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(108, 200, 214, 0.035) 1px, transparent 1px);
        background-size: 38px 38px;
        opacity: 0.4;
        z-index: 0;
    }

    .page, .portal-shell, .dashboard-shell, main {
        background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,250,252,0.98)) !important;
        border-color: var(--border-subtle) !important;
        box-shadow: 0 20px 60px rgba(28, 53, 64, 0.10), 0 0 0 1px rgba(108, 200, 214, 0.10) !important;
    }

    .card, .panel, .section, .content-card, .auth-wrapper .card, .tracker-card,
    .metric-card, .project-card, .schedule-card, .quote-card, .form-card,
    .table-card, .map-card, .automation-card, .status-company {
        background:
            radial-gradient(circle at top left, rgba(108, 200, 214, 0.10), transparent 42%),
            #ffffff !important;
        border-color: var(--border-subtle) !important;
        box-shadow: 0 10px 28px rgba(28, 53, 64, 0.06) !important;
    }

    .brand-logo, .logo-mark, .glow-dot {
        background: radial-gradient(circle at 30% 20%, #ffffff, #9adbe4 42%, #53b8c9 70%, #2a7f96 100%) !important;
        box-shadow: 0 0 18px rgba(108, 200, 214, 0.45), 0 0 34px rgba(108, 200, 214, 0.18) !important;
    }

    .brand-logo::after, .logo-mark::after {
        content: "NP" !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: absolute !important;
        inset: 0 !important;
        border: 0 !important;
        color: #1f5f73 !important;
        font-size: 0.62rem !important;
        font-weight: 900 !important;
        letter-spacing: -0.04em !important;
    }

    h1, h2, h3, h4, h5, h6, .brand-text-main, .card-title, .section-title, .page-title {
        color: #1f3540 !important;
    }

    p, span, small, li, label, .brand-text-sub, .muted, .helptext, .subtitle {
        color: var(--text-muted) !important;
    }

    a, .user-pill a, .nav-link, .link, strong, .accent {
        color: var(--accent-strong) !important;
    }

    .user-pill, .status-company, .message-item, .badge, .pill, .tag {
        background: rgba(255,255,255,0.88) !important;
        border-color: var(--border-strong) !important;
        color: var(--text-main) !important;
    }

    button, .btn, .run-btn, .primary-btn, input[type="submit"], .action-btn {
        background: linear-gradient(135deg, #6cc8d6, #3aa8ba) !important;
        border-color: rgba(31, 142, 168, 0.55) !important;
        color: #ffffff !important;
        box-shadow: 0 10px 24px rgba(58, 168, 186, 0.18) !important;
    }

    button:hover, .btn:hover, .run-btn:hover, .primary-btn:hover, input[type="submit"]:hover, .action-btn:hover {
        box-shadow: 0 0 0 1px rgba(31, 142, 168, 0.24), 0 14px 30px rgba(58, 168, 186, 0.24) !important;
        filter: brightness(1.03);
    }

    input, select, textarea {
        background: #ffffff !important;
        color: var(--text-main) !important;
        border-color: rgba(102, 151, 166, 0.24) !important;
    }

    input:focus, select:focus, textarea:focus {
        border-color: var(--accent-strong) !important;
        box-shadow: 0 0 0 1px rgba(31, 142, 168, 0.30), 0 0 0 4px rgba(108, 200, 214, 0.16) !important;
        outline: none !important;
    }

    table, thead, tbody, tr, td, th {
        color: var(--text-main) !important;
        border-color: rgba(102, 151, 166, 0.18) !important;
    }

    table tr:hover, .automation-row:hover, .order-row:hover, .list-row:hover {
        background: rgba(108, 200, 214, 0.08) !important;
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
