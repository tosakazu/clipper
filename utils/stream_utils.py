from urllib.parse import urlparse, parse_qs

def detect_platform_and_id(url: str) -> tuple[str, str]:
    """
    URLからプラットフォームとストリームIDを検出
    """
    parsed = urlparse(url)
    hostname = parsed.hostname.lower() if parsed.hostname else ""

    if "twitch.tv" in hostname:
        platform = "Twitch"
        path_parts = [p for p in parsed.path.split('/') if p]
        stream_id = path_parts[-1] if path_parts else "unknown_channel"

    elif "youtube.com" in hostname or "youtu.be" in hostname:
        platform = "YouTube"
        if "youtu.be" in hostname:
            path_parts = [p for p in parsed.path.split('/') if p]
            stream_id = path_parts[-1] if path_parts else "unknown_video"
        else:
            qs = parse_qs(parsed.query)
            if 'v' in qs and qs['v']:
                stream_id = qs['v'][0]
            else:
                path_parts = [p for p in parsed.path.split('/') if p]
                stream_id = "_".join(path_parts) if path_parts else "unknown_video"
    else:
        platform = "Other"
        stream_id = "unknown_stream"

    return platform, stream_id