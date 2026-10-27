"""Constant-size process/container observations for the public liveness probe.

No event ledgers, business snapshots, network calls, credentials or plan changes.
"""
import os
import sys
from pathlib import Path


def _small_text(path):
    try:
        with Path(path).open('r',encoding='ascii') as handle:
            return handle.read(128).strip()
    except (OSError,UnicodeError):
        return ''


def _nonnegative(value):
    try:
        number=int(value)
        return number if number>=0 else None
    except (ValueError,TypeError):
        return None


def memory_usage():
    rss=None
    fields=_small_text('/proc/self/statm').split()
    if len(fields)>=2:
        pages=_nonnegative(fields[1])
        try:
            if pages is not None:rss=pages*os.sysconf('SC_PAGE_SIZE')
        except (ValueError,OSError,AttributeError):pass
    peak=None
    try:
        import resource
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak=int(value*(1 if sys.platform=='darwin' else 1024))
    except (ImportError,ValueError,OSError):pass
    current=_nonnegative(_small_text('/sys/fs/cgroup/memory.current'))
    limit=_nonnegative(_small_text('/sys/fs/cgroup/memory.max'))
    return dict(process_rss_bytes=rss,process_peak_rss_bytes=peak,
                container_current_bytes=current,container_limit_bytes=limit,
                container_utilization_pct=round(current/limit*100,2) if current is not None and limit else None,
                scope='PROCESS_RSS_AND_CGROUP_V2_USAGE_INCLUDING_CONTAINER_CACHE',
                unavailable_values_are_null=True)
