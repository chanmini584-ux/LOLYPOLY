"""사진 업로드 검사·재인코딩·저장.

원칙
- 확장자·브라우저가 알려 준 종류는 믿지 않는다. Pillow 로 실제로 열어 JPEG·PNG·WebP 인지 확인한다.
- 받은 파일은 그대로 저장하지 않는다. 방향(EXIF)을 바로잡고 줄인 뒤 새 JPEG 로 다시 만든다.
  이 과정에서 위치·기기 정보 같은 메타데이터가 사라진다.
- 파일 이름은 무작위(UUID)로 만든다. 원래 파일 이름·계정 정보는 어디에도 남기지 않는다.
- 한 번에 푸는 사진 수를 제한해(세마포어) 큰 사진 여러 장이 동시에 와도 메모리가 넘치지 않게 한다.
"""

import io
import threading
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

Image.init()                                        # 형식 해석기를 모두 등록(MPO 는 처음 쓸 때까지 등록되지 않는다)
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}   # MPO = 일부 휴대폰 카메라의 JPEG 변형(첫 장만 사용)
OPEN_FORMATS = [f for f in ("JPEG", "MPO", "PNG", "WEBP") if f in Image.OPEN]
THUMB_EDGE = 480
_decode_slots = threading.BoundedSemaphore(2)


class ImageRejected(Exception):
    """사용자에게 그대로 보여 줄 수 있는 거절 사유."""


@dataclass
class Processed:
    main: bytes
    thumb: bytes
    width: int
    height: int


def _mib(n: int) -> str:
    return f"{n / (1024 * 1024):.0f}MB"


def process(upload) -> Processed:
    """업로드 파일 1개 → 다시 만든 JPEG(본문용·썸네일). 문제가 있으면 ImageRejected."""
    name = "사진"
    if upload.size > settings.COMMUNITY_PHOTO_MAX_BYTES:
        raise ImageRejected(f"{name} 한 장은 {_mib(settings.COMMUNITY_PHOTO_MAX_BYTES)}까지 올릴 수 있어요.")
    if upload.size == 0:
        raise ImageRejected("빈 파일은 올릴 수 없어요.")
    with _decode_slots:
        return _process(upload)


def _process(upload) -> Processed:
    Image.MAX_IMAGE_PIXELS = settings.COMMUNITY_PHOTO_MAX_PIXELS
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(upload, formats=OPEN_FORMATS)
            if img.format not in ALLOWED_FORMATS:
                raise ImageRejected("JPG·PNG·WebP 사진만 올릴 수 있어요.")
            if img.width * img.height > settings.COMMUNITY_PHOTO_MAX_PIXELS:
                raise ImageRejected("사진이 너무 커요(화소 수 초과). 휴대폰 기본 화질로 다시 찍거나 줄여서 올려 주세요.")
            if img.width < 1 or img.height < 1:
                raise ImageRejected("사진을 읽을 수 없어요.")
            if img.format in {"JPEG", "MPO"}:
                img.draft("RGB", (settings.COMMUNITY_PHOTO_MAX_EDGE, settings.COMMUNITY_PHOTO_MAX_EDGE))  # 큰 JPEG 는 줄여서 풀기
            img.load()
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("사진이 너무 커요(화소 수 초과). 휴대폰 기본 화질로 다시 찍거나 줄여서 올려 주세요.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, MemoryError):
        raise ImageRejected("사진 파일이 아니거나 손상됐어요. JPG·PNG·WebP 사진만 올릴 수 있어요. "
                            "아이폰 HEIC 사진은 '가장 호환성 높은 포맷'(JPG)으로 바꿔 올려 주세요.") from None

    try:
        img = ImageOps.exif_transpose(img)            # 눕혀 찍은 사진 바로 세우기
    except Exception:  # noqa: BLE001 — 방향 정보가 깨진 사진은 그대로 둔다
        pass
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))   # 투명한 곳은 흰색
        flat.paste(rgba, mask=rgba.split()[-1])
        img = flat
    else:
        img = img.convert("RGB")
    edge = settings.COMMUNITY_PHOTO_MAX_EDGE
    img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    thumb = img.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
    return Processed(main=_jpeg(img, 85), thumb=_jpeg(thumb, 78), width=img.width, height=img.height)


def _jpeg(img: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    # exif·icc 등 메타데이터를 넘기지 않으므로 새 파일에는 화소 정보만 남는다
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def store(processed: Processed) -> tuple[str, str, str]:
    """다시 만든 사진을 저장하고 (key, 본문용 상대경로, 썸네일 상대경로)를 돌려준다."""
    key = uuid.uuid4()
    now = timezone.localtime()
    rel_dir = Path("community") / f"{now:%Y}" / f"{now:%m}"
    (media_root() / rel_dir).mkdir(parents=True, exist_ok=True)
    main_rel = (rel_dir / f"{key.hex}.jpg").as_posix()
    thumb_rel = (rel_dir / f"{key.hex}_t.jpg").as_posix()
    (media_root() / main_rel).write_bytes(processed.main)
    (media_root() / thumb_rel).write_bytes(processed.thumb)
    return str(key), main_rel, thumb_rel


def remove_files(*rel_paths: str) -> None:
    root = media_root().resolve()
    for rel in rel_paths:
        if not rel:
            continue
        path = (root / rel).resolve()
        if root in path.parents:          # MEDIA_ROOT 밖은 절대 건드리지 않는다
            path.unlink(missing_ok=True)
