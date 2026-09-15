#!/bin/sh
set -eu

# Package the signed app with the documents and license texts users need.
# Usage: scripts/package_macos_app_zip.sh /absolute/path/Neo\ Film\ Bridge.app /absolute/path/nfbridge-vX-preview-macos-arm64-rY.zip

if [ "$#" -ne 2 ]; then
    printf 'Usage: %s APP_PATH OUTPUT_ZIP\n' "$0" >&2
    exit 2
fi

app_path=$1
output_zip=$2
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
release_name=${output_zip##*/}
release_name=${release_name%.zip}

case "$output_zip" in
    /*.zip) ;;
    *) printf 'OUTPUT_ZIP must be an absolute .zip path.\n' >&2; exit 2 ;;
esac
case "$release_name" in
    nfbridge-v*-preview-macos-arm64-r*) ;;
    *) printf 'Unexpected release ZIP name: %s\n' "$release_name" >&2; exit 2 ;;
esac
if [ ! -d "$app_path" ] || [ -e "$output_zip" ]; then
    printf 'App is missing or output ZIP already exists.\n' >&2
    exit 2
fi

staging_root=$(mktemp -d /private/tmp/nfbridge-release.XXXXXX)
trap '/bin/rm -r -- "$staging_root"' EXIT
release_folder="$staging_root/$release_name"
mkdir "$release_folder"

ditto --norsrc --noextattr --noqtn "$app_path" "$release_folder/Neo Film Bridge.app"
for name in LICENSE NOTICE.md README.md README.en.md START_HERE.md START_HERE.en.md \
    RELEASE_NOTES.md RELEASE_NOTES.en.md THIRD_PARTY_NOTICES.md; do
    cp "$source_root/$name" "$release_folder/$name"
done
ditto --norsrc --noextattr --noqtn "$source_root/docs" "$release_folder/docs"
ditto --norsrc --noextattr --noqtn "$source_root/third-party-licenses" "$release_folder/third-party-licenses"

codesign --verify --deep --strict "$release_folder/Neo Film Bridge.app"
COPYFILE_DISABLE=1 ditto --norsrc --noextattr --noqtn -c -k --keepParent "$release_folder" "$output_zip"

unzip -Z1 "$output_zip" > "$staging_root/entries.txt"
for name in 'Neo Film Bridge.app/Contents/Info.plist' LICENSE NOTICE.md README.md \
    README.en.md START_HERE.md START_HERE.en.md RELEASE_NOTES.md \
    RELEASE_NOTES.en.md THIRD_PARTY_NOTICES.md docs/VALIDATION.md \
    third-party-licenses/Python-LICENSE.txt \
    third-party-licenses/pySerial-LICENSE.txt \
    third-party-licenses/tkinterdnd2-LICENSE \
    third-party-licenses/PyInstaller-COPYING.txt \
    third-party-licenses/Tcl-license.terms \
    third-party-licenses/Tk-license.terms; do
    if ! grep -Fqx "$release_name/$name" "$staging_root/entries.txt"; then
        printf 'Release ZIP is missing: %s\n' "$name" >&2
        exit 1
    fi
done
if grep -Eq '(^__MACOSX/|/\._|\.\./)' "$staging_root/entries.txt"; then
    printf 'Release ZIP contains an unwanted metadata or traversal entry.\n' >&2
    exit 1
fi

printf 'Packaged app, guidance and license texts: %s\n' "$output_zip"
