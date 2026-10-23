"""Create a self-signed HTTPS certificate for Expo Design AI on the office network.

    python make_https_cert.py                  (uses this PC's name and IP addresses)
    python make_https_cert.py expo.company.local 10.0.0.25

Writes data/certs/expo.crt and data/certs/expo.key (valid 2 years) and prints the
.env lines to add. Browsers show a warning for self-signed certificates until the
.crt is trusted on each PC (or until IT issues a company certificate - preferred;
put its paths in EXPO_SSL_CERTFILE / EXPO_SSL_KEYFILE instead).
"""
import datetime
import ipaddress
import os
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main(names):
    host = socket.gethostname()
    sans, dns, ips = [], {host, "localhost"}, {"127.0.0.1"}
    try:
        ips.update(i[4][0] for i in socket.getaddrinfo(host, None, socket.AF_INET))
    except OSError:
        pass
    for n in names:
        try:
            ipaddress.ip_address(n); ips.add(n)
        except ValueError:
            dns.add(n)
    sans = [x509.DNSName(d) for d in sorted(dns)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, (names[0] if names else host)),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Expo Design AI (self-signed)")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=730))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "certs")
    os.makedirs(out, exist_ok=True)
    crt, kf = os.path.join(out, "expo.crt"), os.path.join(out, "expo.key")
    with open(kf, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    with open(crt, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    first = names[0] if names else host
    print("Certificate written for:", ", ".join(sorted(dns | ips)))
    print("\nAdd to .env, then run restart.bat:\n")
    print("EXPO_SSL_CERTFILE=data/certs/expo.crt\nEXPO_SSL_KEYFILE=data/certs/expo.key\nEXPO_HTTPS_PORT=8443")
    print(f"EXPO_PUBLIC_URL=https://{first}:8443\n")
    print(f"Other PCs then open https://{first}:8443/ui/app.html (allow port 8443 in Windows Firewall).")


if __name__ == "__main__":
    main(sys.argv[1:])
