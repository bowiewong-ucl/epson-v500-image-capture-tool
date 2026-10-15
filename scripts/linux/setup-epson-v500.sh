#!/usr/bin/env bash
# Set up an Epson Perfection V500 Photo for scanning on Ubuntu / Debian.
#
# The V500 only works with Epson's own "epkowa" SANE driver plus a firmware
# plugin (for the GT-X770, the V500's internal name). Epson's licence doesn't
# allow us to ship them, so download them first:
#
#   1. Go to https://download.ebz.epson.net/dsc/search/01/search/?OSC=LX
#      search for "Perfection V500" and download the
#      "iscan-bundle-<version>.x64.deb.tar.gz" file.
#   2. Run:  sudo bash setup-epson-v500.sh ~/Downloads/iscan-bundle-*.x64.deb.tar.gz
#   3. Unplug and re-plug the scanner, log out and back in, then check with:
#        scanimage -L
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo:  sudo bash $0 <iscan-bundle .tar.gz>" >&2
    exit 1
fi
BUNDLE="${1:-}"
if [ ! -f "$BUNDLE" ]; then
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
fi

echo "==> Installing SANE tools"
apt-get update
apt-get install -y sane-utils

echo "==> Unpacking $BUNDLE"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
tar -xzf "$BUNDLE" -C "$work"
mapfile -t debs < <(find "$work" -name 'iscan_*.deb' -o -name 'iscan-data_*.deb' \
                      -o -name 'iscan-plugin-gt-x770*.deb' -o -name 'esci-interpreter-gt-x770*.deb')
if [ "${#debs[@]}" -eq 0 ]; then
    echo "No iscan / gt-x770 packages found in $BUNDLE. Is it the right download?" >&2
    exit 1
fi
printf '    %s\n' "${debs[@]##*/}"

echo "==> Installing Epson driver and V500 firmware plugin"
apt-get install -y "${debs[@]}"

# Ubuntu looks for SANE backends in the multiarch folder; iscan installs to /usr/lib/sane.
multiarch="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo x86_64-linux-gnu)/sane"
if [ -d "$multiarch" ]; then
    for lib in /usr/lib/sane/libsane-epkowa*; do
        [ -e "$lib" ] && ln -sf "$lib" "$multiarch/"
    done
fi
grep -qx 'epkowa' /etc/sane.d/dll.conf || echo 'epkowa' >> /etc/sane.d/dll.conf

echo "==> Allowing non-root access to the scanner (USB 04b8:0130)"
cat > /etc/udev/rules.d/79-epson-v500.rules <<'EOF'
# Epson Perfection V500 Photo (GT-X770)
ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0130", MODE="0664", GROUP="scanner", ENV{libsane_matched}="yes"
EOF
getent group scanner >/dev/null || groupadd --system scanner
if [ -n "${SUDO_USER:-}" ]; then
    usermod -aG scanner,lp "$SUDO_USER"
fi
udevadm control --reload-rules
udevadm trigger

echo
echo "Done. Now unplug and re-plug the scanner, log out and back in, then run:"
echo "    scanimage -L"
echo "It should list an 'epkowa:...' device for the Perfection V500."
