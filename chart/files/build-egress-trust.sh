#!/bin/sh
# This store contains public inspection roots only. Never copy the image's public CA store.
set -eu
umask 022
source_file=$1
store_file=$2
certificate_file="${store_file}.pem"
trap 'rm -f "$certificate_file"' EXIT
rm -f "$store_file"
count=0
inside=false
while IFS= read -r line || [ -n "$line" ]; do
    if [ "$line" = '-----BEGIN CERTIFICATE-----' ]; then
        [ "$inside" = false ] || exit 1
        inside=true
        : > "$certificate_file"
    fi
    if [ "$inside" = true ]; then
        printf '%s\n' "$line" >> "$certificate_file"
    fi
    if [ "$line" = '-----END CERTIFICATE-----' ]; then
        [ "$inside" = true ] || exit 1
        count=$((count + 1))
        keytool -importcert -noprompt -alias "inspection-$count" -file "$certificate_file" \
            -keystore "$store_file" -storetype PKCS12 -storepass changeit
        inside=false
    fi
done < "$source_file"
[ "$inside" = false ] && [ "$count" -gt 0 ]
chmod 0444 "$store_file"
