#!/usr/bin/env sh
set -eu

allowed_ips="${WEB_ADMIN_ALLOWED_IPS:-}"
upstream="${WEB_ADMIN_UPSTREAM:-http://web:8080}"
allow_rules=""

if [ -n "$allowed_ips" ]; then
    old_ifs="$IFS"
    IFS=","
    for ip in $allowed_ips; do
        clean_ip="$(printf '%s' "$ip" | tr -d '[:space:]')"
        if [ -n "$clean_ip" ]; then
            allow_rules="${allow_rules}        allow ${clean_ip};
"
        fi
    done
    IFS="$old_ifs"
    allow_rules="${allow_rules}        deny all;"
fi

cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 80;
    server_name _;

    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log warn;

    location / {
${allow_rules}
        proxy_pass ${upstream};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
EOF

nginx -t
