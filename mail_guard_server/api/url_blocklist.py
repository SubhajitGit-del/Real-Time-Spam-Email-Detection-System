# api/url_blocklist.py
"""
This module checks URLs and sender domains against
predefined benign and malicious domain lists.
"""

from pathlib import Path
import re
import tldextract

# -------------------------------------------------
# File paths
# -------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent / "data"

BENIGN_TXT_PATH = DATA_DIR / "benign_hosts.txt"
MALICIOUS_TXT_PATH = DATA_DIR / "malicious_hosts.txt"

# -------------------------------------------------
# In-memory sets (fast lookup)
# -------------------------------------------------
BENIGN_ROOTS: set[str] = set()
MALICIOUS_ROOTS: set[str] = set()

# -------------------------------------------------
# URL extraction regex
# -------------------------------------------------
URL_REGEX = re.compile(
    r"""(?P<url>
        https?://[^\s<>"']+|
        www\.[^\s<>"']+
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# -------------------------------------------------
# Helper functions
# -------------------------------------------------

def _extract_root_domain(value: str) -> str | None:
    """
    Converts full URL or hostname to root domain.

    Examples:
      https://mail.google.com  -> google.com
      www.amazon.in           -> amazon.in
    """

    if not value:
        return None

    value = str(value).strip()
    if not value:
        return None

    ext = tldextract.extract(value)

    if not ext.domain or not ext.suffix:
        return None

    return f"{ext.domain}.{ext.suffix}".lower()


def _get_sender_domain(sender: str) -> str | None:
    """
    Extracts domain from email address.

    Example:
      user@gmail.com -> gmail.com
    """

    if not sender:
        return None

    match = re.search(r"@([A-Za-z0-9\.-]+)", sender)
    if not match:
        return None

    return match.group(1).lower()


# -------------------------------------------------
# Load domain lists into memory
# -------------------------------------------------

def _load_blocklists():
    """Loads benign and malicious domains from text files"""

    global BENIGN_ROOTS, MALICIOUS_ROOTS

    benign = set()
    malicious = set()

    # Load benign domains
    if BENIGN_TXT_PATH.exists():
        for line in BENIGN_TXT_PATH.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            if line.strip():
                benign.add(line.strip().lower())
    else:
        print("[url_blocklist] Benign file missing")

    # Load malicious domains
    if MALICIOUS_TXT_PATH.exists():
        for line in MALICIOUS_TXT_PATH.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            if line.strip():
                malicious.add(line.strip().lower())
    else:
        print("[url_blocklist] Malicious file missing")

    BENIGN_ROOTS = benign
    MALICIOUS_ROOTS = malicious

    print(
        f"[url_blocklist] Loaded "
        f"{len(MALICIOUS_ROOTS)} malicious & "
        f"{len(BENIGN_ROOTS)} benign domains"
    )


# Load lists on startup
_load_blocklists()


# -------------------------------------------------
# Public functions used by views.py
# -------------------------------------------------

def extract_hosts(sender: str, body: str) -> set[str]:
    """
    Extracts all root domains from:
    - sender email
    - URLs inside email body
    """

    roots = set()

    # Sender domain
    sender_domain = _get_sender_domain(sender)
    if sender_domain:
        root = _extract_root_domain(sender_domain)
        if root:
            roots.add(root)

    # URLs from body
    for match in URL_REGEX.finditer(body or ""):
        url = match.group("url")
        root = _extract_root_domain(url)
        if root:
            roots.add(root)

    return roots


def assess_urls(sender: str, body: str) -> dict:
    """
    Final URL assessment function.

    Returns:
    {
      status: malicious / benign / unknown
      hosts: all domains found
      malicious_hosts: matched blacklist
      benign_hosts: matched whitelist
    }
    """

    roots = extract_hosts(sender, body)

    malicious_hits = [h for h in roots if h in MALICIOUS_ROOTS]
    benign_hits = [h for h in roots if h in BENIGN_ROOTS]

    if malicious_hits:
        status = "malicious"
    elif benign_hits:
        status = "benign"
    else:
        status = "unknown"

    return {
        "status": status,
        "hosts": sorted(roots),
        "malicious_hosts": sorted(malicious_hits),
        "benign_hosts": sorted(benign_hits),
    }


