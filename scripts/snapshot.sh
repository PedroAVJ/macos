#!/usr/bin/env bash
# Read-only MacBook diagnostics snapshot.
#
#   snapshot.sh memory        pressure, swap, compression, resident processes
#   snapshot.sh storage       APFS headroom, durable leads, cache fallbacks
#   snapshot.sh all           every section (default)
#
# Nothing here mutates state, kills processes, or triggers macOS Automation
# prompts.
set -u

MODE="${1:-all}"

section() {
  printf '\n%s\n%s\n%s\n' \
    "============================================================" \
    "$1" \
    "------------------------------------------------------------"
}

want() {
  [[ "$MODE" == "all" || "$MODE" == "$1" ]]
}

case "$MODE" in
  memory|storage|all) ;;
  *)
    printf 'usage: %s [memory|storage|all]\n' "${0##*/}" >&2
    exit 2
    ;;
esac

now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
host="$(scutil --get ComputerName 2>/dev/null || hostname)"
mem_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
mem_gb="$(awk -v b="$mem_bytes" 'BEGIN { printf "%.1f", b / 1024 / 1024 / 1024 }')"
cpu_count="$(sysctl -n hw.ncpu 2>/dev/null || echo unknown)"
model="$(sysctl -n hw.model 2>/dev/null || echo unknown)"

printf 'macbook_snapshot mode=%s %s\n' "$MODE" "$now"
printf 'host=%s model=%s cpu_count=%s ram=%sGB\n' "$host" "$model" "$cpu_count" "$mem_gb"
uptime

# -------------------------------------------------------------- memory

if want memory; then
  section "Kernel Memory Pressure (Primary)"
  pressure_level="$(sysctl -n kern.memorystatus_vm_pressure_level 2>/dev/null || true)"
  case "$pressure_level" in
    0)
      pressure_state="normal"
      userspace_class="normal"
      activity_color="green"
      ;;
    1)
      pressure_state="warning"
      userspace_class="warning"
      activity_color="yellow"
      ;;
    2)
      pressure_state="urgent"
      userspace_class="warning"
      activity_color="yellow"
      ;;
    3)
      pressure_state="critical"
      userspace_class="critical"
      activity_color="red"
      ;;
    4)
      pressure_state="jetsam_approaching"
      userspace_class="internal_severe"
      activity_color="none"
      ;;
    *)
      pressure_level="unavailable"
      pressure_state="unknown"
      userspace_class="unknown"
      activity_color="unknown"
      ;;
  esac
  printf 'kernel_memory_pressure_level=%s state=%s userspace_class=%s activity_monitor_color=%s\n' \
    "$pressure_level" "$pressure_state" "$userspace_class" "$activity_color"
  printf 'kernel_pressure_levels=0:normal,1:warning,2:urgent-warning,3:critical,4:jetsam-approaching\n'

  section "System Memory"
  memory_pressure 2>/dev/null | tail -24 || true
  sysctl vm.swapusage 2>/dev/null || true

  page_size="$(vm_stat 2>/dev/null | awk '/page size of/ { gsub(/[^0-9]/, "", $8); print $8; exit }')"
  compressed_pages="$(vm_stat 2>/dev/null | awk -F: '/Pages occupied by compressor/ { gsub(/[^0-9]/, "", $2); print $2; exit }')"
  free_pages="$(vm_stat 2>/dev/null | awk -F: '/Pages free/ { gsub(/[^0-9]/, "", $2); print $2; exit }')"
  [[ -n "${page_size:-}" && -n "${compressed_pages:-}" ]] && \
    awk -v p="$page_size" -v c="$compressed_pages" 'BEGIN { printf "compressed_occupied=%.1fMB\n", (p*c)/1024/1024 }'
  [[ -n "${page_size:-}" && -n "${free_pages:-}" ]] && \
    awk -v p="$page_size" -v f="$free_pages" 'BEGIN { printf "free_pages_memory=%.1fMB\n", (p*f)/1024/1024 }'

  section "Large Resident Processes"
  ps -axo pid=,ppid=,etime=,stat=,pcpu=,pmem=,rss=,comm= \
    | awk '$7 > 100000 { printf "%7s ppid=%-7s age=%-12s stat=%-5s cpu=%5.1f mem=%4.1f rss=%7.1fMB %s\n", $1,$2,$3,$4,$5,$6,$7/1024,$8 }' \
    | sort -k7,7nr | head -40

  section "Swap Verdict"
  swap_used="$(sysctl vm.swapusage 2>/dev/null | awk -F'used = ' '{print $2}' | awk '{print $1}' | sed 's/M//')"
  if [[ -n "${swap_used:-}" && "$mem_bytes" -gt 0 ]]; then
    awk -v s="$swap_used" -v b="$mem_bytes" 'BEGIN {
      ram_mb=b/1024/1024
      ratio=s/ram_mb
      if (ratio >= 0.75) verdict="high_ratio"
      else if (ratio >= 0.50) verdict="heavy_ratio"
      else if (ratio >= 0.25) verdict="pressured_ratio"
      else verdict="acceptable_ratio"
      printf "swap_used_mb=%.1f physical_ram_mb=%.1f swap_to_ram_pct=%.1f verdict=%s\n", s, ram_mb, ratio*100, verdict
    }'
  fi
fi

# ------------------------------------------------------------- storage

if want storage; then
  storage_target_pct=20

  section "APFS Headroom (Swap Ceiling)"
  df -h /System/Volumes/Data /System/Volumes/VM 2>/dev/null || true
  diskutil apfs list 2>/dev/null | grep -E "Capacity (In Use|Not Allocated)" || true

  section "Data Volume Free-Capacity Target"
  df -Pk /System/Volumes/Data 2>/dev/null | awk -v target_pct="$storage_target_pct" 'NR == 2 {
    total_kb=$2; available_kb=$4; free_pct=(available_kb/total_kb)*100
    target_kb=total_kb*(target_pct/100)
    shortfall_kb=target_kb-available_kb
    if (shortfall_kb < 0) shortfall_kb=0
    if (free_pct >= target_pct) target_state="met"
    else target_state="below"
    printf "total_gb=%.1f available_gb=%.1f free_pct=%.1f target_pct=%.1f target_gb=%.1f shortfall_gb=%.1f target_state=%s\n", total_kb/1024/1024, available_kb/1024/1024, free_pct, target_pct, target_kb/1024/1024, shortfall_kb/1024/1024, target_state
  }'

  section "Local Snapshots"
  tmutil listlocalsnapshots / 2>/dev/null || true

  section "Durable-Reclaim Review Pools"
  for d in \
    "$HOME/Downloads" \
    "$HOME/.Trash" \
    "$HOME/Documents/Codex" \
    "$HOME/.codex/sessions" \
    "$HOME/.codex/worktrees" \
    "$HOME/.claude/worktrees"
  do
    [[ -d "$d" ]] && printf '%8s  %s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$d"
  done

  section "Largest Finished-Download Candidates"
  du -sh "$HOME"/Downloads/* /Applications/*.dmg 2>/dev/null | sort -hr | head -15 || true

  section "Regenerable Fallbacks (Expected to Return)"
  for d in \
    /private/tmp \
    "$HOME/Library/Developer/Xcode/DerivedData" \
    "$HOME/Library/Caches" \
    "$HOME/Library/Containers/com.apple.CoreSimulator" \
    "$HOME/.cache" \
    "$HOME/Library/Application Support/Code/Cache"
  do
    [[ -d "$d" ]] && printf '%8s  %s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$d"
  done

  section "Largest Regenerable Directories Under /private/tmp"
  du -sh /private/tmp/* 2>/dev/null | sort -hr | head -15 || true
fi
