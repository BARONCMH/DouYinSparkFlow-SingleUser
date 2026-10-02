# The single-user sender still imports the compatibility name used by the
# server worker.  Keep one implementation in core.douyin_im.
from core.douyin_im import norm

__all__ = ["norm"]
