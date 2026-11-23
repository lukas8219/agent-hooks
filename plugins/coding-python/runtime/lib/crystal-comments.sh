crystal_comments() {
  command -v crystal >/dev/null || return 0
  local source cache key binary build
  source=$here/../lib/crystal-comments.cr
  cache=${XDG_CACHE_HOME:-${HOME}/.cache}/agent-hooks
  key=$({ cat "$source"; crystal --version; } | cksum | awk '{print $1}')
  binary=$cache/crystal-comments-$key
  if [ ! -x "$binary" ]; then
    mkdir -p "$cache" || return 0
    build=$(mktemp -d "$cache/build.XXXXXX") || return 0
    if crystal build "$source" -o "$build/comments" >&2; then
      mv "$build/comments" "$binary"
    fi
    rm -rf "$build"
  fi
  [ -x "$binary" ] && "$binary"
}
