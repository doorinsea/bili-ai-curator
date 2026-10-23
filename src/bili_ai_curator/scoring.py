from __future__ import annotations

from statistics import fmean

from .models import VideoCandidate


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def percentile_rank(value: float, peers: list[float]) -> float:
    if not peers:
        return 0.5
    return sum(1 for peer in peers if peer <= value) / len(peers)


def score_popularity(
    *, age_hours: float, views: float, peer_views: list[float]
) -> float:
    view_percentile = percentile_rank(views, peer_views)
    freshness = 1.0 / (1.0 + max(0.0, age_hours) / 72.0)
    return _clamp(0.7 * view_percentile + 0.3 * freshness)


def engagement_score(video: VideoCandidate, peer_videos: list[VideoCandidate]) -> float:
    def ratio(item: VideoCandidate) -> float:
        return (item.likes + item.comments * 2) / max(item.views, 1)

    current = ratio(video)
    peers = [ratio(item) for item in peer_videos if item.bvid != video.bvid]
    if not peers:
        return 0.5
    return _clamp(percentile_rank(current, peers))


def final_score(
    *,
    relevance: float,
    interest: float,
    popularity: float,
    engagement: float,
    freshness: float,
    diversity: float,
) -> float:
    return _clamp(
        0.30 * relevance
        + 0.25 * interest
        + 0.20 * popularity
        + 0.10 * engagement
        + 0.10 * freshness
        + 0.05 * diversity
    )


def matches_topic(
    video: VideoCandidate, keywords: tuple[str, ...], exclude: tuple[str, ...]
) -> bool:
    raw = video.raw if isinstance(video.raw, dict) else {}
    tags = raw.get("tags") or []
    text = " ".join(
        [
            video.title,
            str(raw.get("desc") or ""),
            " ".join(str(tag) for tag in tags),
        ]
    ).lower()
    if any(word.lower() in text for word in exclude):
        return False
    return any(word.lower() in text for word in keywords)


def source_diversity_score(source_count: int) -> float:
    return _clamp(source_count / 3.0)


def peer_median(peer_views: list[float]) -> float:
    return fmean(peer_views) if peer_views else 0.0
