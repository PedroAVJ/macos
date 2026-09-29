#!/bin/bash
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec "$plugin_root/bin/contacts" "$@"
