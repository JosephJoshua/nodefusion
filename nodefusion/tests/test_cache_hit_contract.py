from types import SimpleNamespace as NS

from nodefusion.host.analyze import Analysis, Event
from nodefusion.model.manifest import load_dir


def _metrics(method):
    a = object.__new__(Analysis)
    a.cache_hit_derivation = method
    a.trace = NS(total_insns=100, nftrace=[], end=NS(watch_drops=0))
    a.events = [Event(i, 0, "bcache.read", "bcache") for i in range(3)]
    a.events.append(Event(4, 0, "disk.io", "disk",
                          detail={"operation": "read"}))
    a._watched_kinds = lambda: {"bcache.read", "disk.io"}
    a._sampled_kinds = lambda: {}
    a._unobservable_reason = lambda m: None
    a._absent_kinds = lambda: {}
    return a.metrics()


def test_cache_hit_subtraction_requires_a_one_to_one_source_contract():
    assert _metrics("one_to_one")["bcache_hits"] == 2
    assert _metrics("one_to_one")["bcache_hit_rate"] == 2 / 3
    assert _metrics("unverified")["bcache_hits"] is None
    assert _metrics("unverified")["bcache_hit_rate"] is None


def test_semantic_cache_outcomes_count_requests_not_batched_device_calls():
    a = object.__new__(Analysis)
    a.cache_hit_derivation = "semantic"
    a.trace = NS(total_insns=100, end=NS(watch_drops=0), nftrace=[
        NS(type=Analysis.NFT_CACHE_READ, a=(1, 10, 1, 0)),
        NS(type=Analysis.NFT_CACHE_READ, a=(0, 11, 4, 0)),
        NS(type=Analysis.NFT_CACHE_READ, a=(1, 12, 1, 0)),
    ])
    a.events = [Event(i, 0, "bcache.read", "bcache") for i in range(3)]
    a.events.append(Event(4, 0, "disk.io", "disk",
                          detail={"operation": "read"}))
    a._watched_kinds = lambda: {"bcache.read", "disk.io"}
    a._sampled_kinds = lambda: {}
    a._unobservable_reason = lambda m: None
    a._absent_kinds = lambda: {}
    assert a.metrics()["bcache_hits"] == 2
    assert a.metrics()["bcache_hit_rate"] == 2 / 3
    a.trace.nftrace.pop()
    assert a.metrics()["bcache_hits"] is None


def test_failed_cache_requests_do_not_enter_the_hit_rate_denominator():
    a = object.__new__(Analysis)
    a.cache_hit_derivation = "semantic"
    a.trace = NS(total_insns=100, end=NS(watch_drops=0), nftrace=[
        NS(type=Analysis.NFT_CACHE_READ, a=(1, 10, 1, 0)),
        NS(type=Analysis.NFT_CACHE_READ, a=(2, 11, 1, 0)),
    ])
    a.events = [Event(i, 0, "bcache.read", "bcache") for i in range(2)]
    a._watched_kinds = lambda: {"bcache.read"}
    a._sampled_kinds = lambda: {}
    a._unobservable_reason = lambda m: None
    a._absent_kinds = lambda: {}
    metrics = a.metrics()
    assert metrics["bcache_hits"] == 1
    assert metrics["bcache_hit_rate"] is None


def test_more_device_reads_than_cache_requests_is_not_clamped_to_zero():
    a = object.__new__(Analysis)
    a.cache_hit_derivation = "one_to_one"
    a.trace = NS(total_insns=100, nftrace=[], end=NS(watch_drops=0))
    a.events = [Event(1, 0, "bcache.read", "bcache")]
    a.events.extend(Event(i, 0, "disk.io", "disk",
                          detail={"operation": "read"}) for i in (2, 3))
    a._watched_kinds = lambda: {"bcache.read", "disk.io"}
    a._sampled_kinds = lambda: {}
    a._unobservable_reason = lambda m: None
    a._absent_kinds = lambda: {}
    assert a.metrics()["bcache_hits"] is None


def test_starry_batched_io_does_not_claim_exact_cache_hits():
    manifests = load_dir()
    assert manifests["starry"].cache_hit_derivation == "semantic"
    assert manifests["ucore"].cache_hit_derivation == "one_to_one"
    assert manifests["rcore"].cache_hit_derivation == "one_to_one"
    assert manifests["starry"].clone_completion_channel == "nftrace"
    assert manifests["ucore"].clone_completion_channel == "nftrace"
    assert manifests["rcore"].clone_completion_channel == "entry"
