"""
تبدیل فایل کوکی JSON (خروجی اکستنشن‌هایی مثل Cookie-Editor / EditThisCookie)
به فرمت Netscape که yt-dlp نیاز داره.

استفاده:
    python3 json2netscape.py instagram.json instagram.txt
"""
import json
import sys


def convert(json_path: str, txt_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    if isinstance(cookies, dict):
        # بعضی اکستنشن‌ها { "cookies": [...] } برمی‌گردونن
        cookies = cookies.get("cookies", [])

    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.get("domain", "")
        host_only = c.get("hostOnly", not domain.startswith("."))

        if host_only:
            include_subdomains = "FALSE"
            domain = domain.lstrip(".")
        else:
            include_subdomains = "TRUE"
            if not domain.startswith("."):
                domain = "." + domain

        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"

        if c.get("session") or "expirationDate" not in c:
            expiry = "0"
        else:
            expiry = str(int(float(c["expirationDate"])))

        name = c.get("name", "")
        value = c.get("value", "")

        lines.append("\t".join([domain, include_subdomains, path, secure, expiry, name, value]))

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"ذخیره شد: {txt_path} ({len(cookies)} کوکی)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("استفاده: python3 json2netscape.py input.json output.txt")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
